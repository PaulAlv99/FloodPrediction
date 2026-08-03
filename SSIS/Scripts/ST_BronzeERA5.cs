using System;
using System.Collections.Generic;
using System.Data;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Data.SqlClient;
using Microsoft.SqlServer.Dts.Runtime;

public void Main()
{
    string runId = Guid.NewGuid().ToString();
    string connStr = "Server=localhost;Database=PreFlood_DW;Trusted_Connection=yes;";
    string landingDir = @"C:\ProjetoDW\V4\Landing";
    string pythonExe = "python";
    int delayDays = 7;

    double latMin = 40.04, latMax = 40.63, lonMin = -8.89, lonMax = -6.82;

    Dts.Variables["User::RunId"].Value = runId;

    ETLLogInicio(connStr, runId, "EXTRACAO", "API->Bronze ERA5");
    try
    {
        string era5Dir = Path.Combine(landingDir, "ERA5");
        Directory.CreateDirectory(era5Dir);
        string timestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
        string runDir = Path.Combine(era5Dir, timestamp);
        Directory.CreateDirectory(runDir);

        bool fireAgain = true;
        Dts.Events.FireInformation(0, "ST_BronzeERA5",
            string.Format("Starting Bronze download. RunId={0} Delay={1}d Region=[{2},{3}]-[{4},{5}]",
                runId, delayDays, latMin, lonMin, latMax, lonMax), "", 0, ref fireAgain);

        var pontos = GetPontos(connStr, latMin, latMax, lonMin, lonMax);
        Dts.Events.FireInformation(0, "ST_BronzeERA5",
            string.Format("Found {0} coordinate points in Coimbra region from Bronze tables", pontos.Count), "", 0, ref fireAgain);

        if (pontos.Count == 0)
        {
            Dts.Events.FireError(0, "ST_BronzeERA5",
                "No station coordinates found in Bronze tables for the specified region. " +
                "Ensure ST_BronzeIPMA and ST_BronzeSNIRH have completed successfully.", "", 0);
            Dts.TaskResult = (int)ScriptResults.Failure;
            return;
        }

        DateTime targetDate = DateTime.Now.AddDays(-delayDays);
        string year = targetDate.Year.ToString();
        string month = targetDate.Month.ToString().PadLeft(2, '0');
        string day = targetDate.Day.ToString().PadLeft(2, '0');

        string tempScript = Path.Combine(runDir, "era5_download.py");
        File.WriteAllText(tempScript,
            GeneratePythonScript(pontos, year, month, day, runDir), Encoding.UTF8);

        Dts.Events.FireInformation(0, "ST_BronzeERA5",
            string.Format("Running Python script for date {0}-{1}-{2}", year, month, day), "", 0, ref fireAgain);

        var proc = new Process();
        proc.StartInfo.FileName = pythonExe;
        proc.StartInfo.Arguments = string.Format("\"{0}\"", tempScript);
        proc.StartInfo.UseShellExecute = false;
        proc.StartInfo.RedirectStandardOutput = true;
        proc.StartInfo.RedirectStandardError = true;
        proc.StartInfo.CreateNoWindow = true;
        proc.Start();
        string output = proc.StandardOutput.ReadToEnd();
        string errors = proc.StandardError.ReadToEnd();
        proc.WaitForExit(600000);

        if (!string.IsNullOrEmpty(output))
            Dts.Events.FireInformation(0, "ST_BronzeERA5", "Python stdout: " + output, "", 0, ref fireAgain);
        if (!string.IsNullOrEmpty(errors))
            Dts.Events.FireWarning(0, "ST_BronzeERA5", "Python stderr: " + errors, "", 0);

        if (proc.ExitCode != 0)
            throw new Exception(string.Format(
                "ERA5 Python download failed (exit {0}): {1}", proc.ExitCode, errors));

        int totalRows = ParseCSVs(connStr, runDir, runId);
        Dts.Variables["User::RowCount"].Value = totalRows;

        ETLLogFim(connStr, runId, "EXTRACAO", "API->Bronze ERA5", "OK", totalRows, totalRows, 0, null);

        Dts.Events.FireInformation(0, "ST_BronzeERA5",
            string.Format("Bronze complete. Total rows: {0}", totalRows), "", 0, ref fireAgain);
        Dts.TaskResult = (int)ScriptResults.Success;
    }
    catch (Exception ex)
    {
        Dts.Variables["User::ErrorMsg"].Value = ex.Message;
        ETLLogErro(connStr, runId, "EXTRACAO", "API->Bronze ERA5", 0, ex.Message, 0);
        Dts.Events.FireError(0, "ST_BronzeERA5", ex.Message, "", 0);
        Dts.TaskResult = (int)ScriptResults.Failure;
    }
}

List<string[]> GetPontos(string connStr, double latMin, double latMax, double lonMin, double lonMax)
{
    var pontos = new List<string[]>();
    using (var conn = new SqlConnection(connStr))
    {
        conn.Open();
        using (var cmd = new SqlCommand(
            @"SELECT DISTINCT latitude, longitude FROM brz.ipma_est
              WHERE latitude IS NOT NULL AND latitude <> '' AND ISNUMERIC(latitude) = 1
                AND CAST(latitude AS FLOAT) BETWEEN @latMin AND @latMax
                AND CAST(longitude AS FLOAT) BETWEEN @lonMin AND @lonMax
              UNION
              SELECT DISTINCT latitude, longitude FROM brz.snirh_est
              WHERE latitude IS NOT NULL AND latitude <> '' AND ISNUMERIC(latitude) = 1
                AND CAST(latitude AS FLOAT) BETWEEN @latMin AND @latMax
                AND CAST(longitude AS FLOAT) BETWEEN @lonMin AND @lonMax", conn))
        {
            cmd.Parameters.AddWithValue("@latMin", latMin);
            cmd.Parameters.AddWithValue("@latMax", latMax);
            cmd.Parameters.AddWithValue("@lonMin", lonMin);
            cmd.Parameters.AddWithValue("@lonMax", lonMax);
            using (var rdr = cmd.ExecuteReader())
            {
                while (rdr.Read())
                {
                    double lat = Math.Round(Convert.ToDouble(rdr["latitude"], CultureInfo.InvariantCulture), 1);
                    double lon = Math.Round(Convert.ToDouble(rdr["longitude"], CultureInfo.InvariantCulture), 1);
                    pontos.Add(new[] {
                        lat.ToString(CultureInfo.InvariantCulture),
                        lon.ToString(CultureInfo.InvariantCulture)
                    });
                }
            }
        }
    }
    return pontos;
}

string GeneratePythonScript(List<string[]> pontos, string year, string month, string day, string outputDir)
{
    string dateStr = string.Format("{0}-{1}-{2}/{0}-{1}-{2}", year, month, day);
    var sb = new StringBuilder();
    sb.AppendLine("import cdsapi");
    sb.AppendLine("import os");
    sb.AppendLine("import sys");
    sb.AppendLine();
    sb.AppendLine("client = cdsapi.Client()");

    for (int i = 0; i < pontos.Count; i++)
    {
        string lat = pontos[i][0];
        string lon = pontos[i][1];
        string outFile = string.Format("era5_pt{0}_{1}_{2}.csv", i, lat, lon);

        sb.AppendLine();
        sb.AppendLine("try:");
        sb.AppendLine("    client.retrieve(");
        sb.AppendLine("        'reanalysis-era5-land-timeseries',");
        sb.AppendLine("        {");
        sb.AppendLine("            'variable': [");
        sb.AppendLine("                '2m_temperature',");
        sb.AppendLine("                'total_precipitation',");
        sb.AppendLine("                'volumetric_soil_water_layer_1',");
        sb.AppendLine("                'volumetric_soil_water_layer_2',");
        sb.AppendLine("                'volumetric_soil_water_layer_3',");
        sb.AppendLine("                'volumetric_soil_water_layer_4',");
        sb.AppendLine("                'surface_pressure',");
        sb.AppendLine("            ],");
        sb.AppendLine(string.Format("            'location': {{'latitude': {0}, 'longitude': {1}}},", lat, lon));
        sb.AppendLine(string.Format("            'date': ['{0}'],", dateStr));
        sb.AppendLine("            'data_format': 'csv',");
        sb.AppendLine("        },");
        sb.AppendLine(string.Format("        os.path.join(r'{0}', '{1}'))", outputDir, outFile));
        sb.AppendLine(string.Format("    print('Downloaded point {0}')", i));
        sb.AppendLine("except Exception as e:");
        sb.AppendLine(string.Format("    print('ERROR point {0}: ' + str(e), file=sys.stderr)", i));
    }
    return sb.ToString();
}

int ParseCSVs(string connStr, string runDir, string runId)
{
    int totalRows = 0;
    string[] csvFiles = Directory.GetFiles(runDir, "era5_*.csv");

    using (var conn = new SqlConnection(connStr))
    {
        conn.Open();
        using (var cmd = new SqlCommand(
            @"INSERT INTO brz.era5_obs
              (data_hora, latitude, longitude, temperatura_2m, precipitacao,
               solo_l1, solo_l2, solo_l3, solo_l4, pressao_superf, _arquivo, _run_id)
              VALUES (@dt, @lat, @lon, @t2m, @tp, @l1, @l2, @l3, @l4, @sp, @arquivo, @runId)", conn))
        {
            cmd.Parameters.Add("@dt", SqlDbType.NVarChar, 30);
            cmd.Parameters.Add("@lat", SqlDbType.NVarChar, 20);
            cmd.Parameters.Add("@lon", SqlDbType.NVarChar, 20);
            cmd.Parameters.Add("@t2m", SqlDbType.NVarChar, 20);
            cmd.Parameters.Add("@tp", SqlDbType.NVarChar, 20);
            cmd.Parameters.Add("@l1", SqlDbType.NVarChar, 20);
            cmd.Parameters.Add("@l2", SqlDbType.NVarChar, 20);
            cmd.Parameters.Add("@l3", SqlDbType.NVarChar, 20);
            cmd.Parameters.Add("@l4", SqlDbType.NVarChar, 20);
            cmd.Parameters.Add("@sp", SqlDbType.NVarChar, 20);
            cmd.Parameters.Add("@arquivo", SqlDbType.NVarChar, 500);
            cmd.Parameters.Add("@runId", SqlDbType.UniqueIdentifier);
            cmd.Parameters["@runId"].Value = Guid.Parse(runId);

            foreach (string csvFile in csvFiles)
            {
                string[] lines = File.ReadAllLines(csvFile);
                if (lines.Length < 2) continue;
                cmd.Parameters["@arquivo"].Value = csvFile;

                int dateCol = -1, latCol = -1, lonCol = -1;
                int t2mCol = -1, tpCol = -1, spCol = -1;
                int l1Col = -1, l2Col = -1, l3Col = -1, l4Col = -1;
                int headerLine = -1;

                for (int i = 0; i < Math.Min(lines.Length, 20); i++)
                {
                    string ln = lines[i].Trim();
                    if (ln.StartsWith("#") || string.IsNullOrEmpty(ln)) continue;
                    if (ln.ToLowerInvariant().Contains("temperature") || ln.ToLowerInvariant().Contains("latitude"))
                    {
                        headerLine = i;
                        string[] headers = ln.Split(',');
                        for (int c = 0; c < headers.Length; c++)
                        {
                            string h = headers[c].Trim().ToLowerInvariant();
                            if (h.Contains("time") && !h.Contains("surface") && dateCol < 0) dateCol = c;
                            else if (h.Contains("latitude") && latCol < 0) latCol = c;
                            else if (h.Contains("longitude") && lonCol < 0) lonCol = c;
                            else if (h.Contains("2m_temperature") && t2mCol < 0) t2mCol = c;
                            else if (h.Contains("total_precipitation") && tpCol < 0) tpCol = c;
                            else if (h.Contains("surface_pressure") && spCol < 0) spCol = c;
                            else if (h.Contains("soil_water_layer_1") && l1Col < 0) l1Col = c;
                            else if (h.Contains("soil_water_layer_2") && l2Col < 0) l2Col = c;
                            else if (h.Contains("soil_water_layer_3") && l3Col < 0) l3Col = c;
                            else if (h.Contains("soil_water_layer_4") && l4Col < 0) l4Col = c;
                        }
                        break;
                    }
                }

                if (headerLine < 0 || dateCol < 0)
                {
                    Dts.Events.FireWarning(0, "ST_BronzeERA5",
                        string.Format("Could not parse header in {0}", Path.GetFileName(csvFile)), "", 0);
                    continue;
                }

                for (int i = headerLine + 1; i < lines.Length; i++)
                {
                    string line = lines[i].Trim();
                    if (string.IsNullOrEmpty(line) || line.StartsWith("#")) continue;
                    string[] cols = line.Split(',');
                    if (cols.Length < 4) continue;
                    if (dateCol >= cols.Length || string.IsNullOrWhiteSpace(cols[dateCol])) continue;

                    cmd.Parameters["@dt"].Value = cols[dateCol].Trim();
                    cmd.Parameters["@lat"].Value = latCol >= 0 && latCol < cols.Length ? cols[latCol].Trim() : "";
                    cmd.Parameters["@lon"].Value = lonCol >= 0 && lonCol < cols.Length ? cols[lonCol].Trim() : "";
                    cmd.Parameters["@t2m"].Value = (object)SafeCol(cols, t2mCol) ?? DBNull.Value;
                    cmd.Parameters["@tp"].Value = (object)SafeCol(cols, tpCol) ?? DBNull.Value;
                    cmd.Parameters["@l1"].Value = (object)SafeCol(cols, l1Col) ?? DBNull.Value;
                    cmd.Parameters["@l2"].Value = (object)SafeCol(cols, l2Col) ?? DBNull.Value;
                    cmd.Parameters["@l3"].Value = (object)SafeCol(cols, l3Col) ?? DBNull.Value;
                    cmd.Parameters["@l4"].Value = (object)SafeCol(cols, l4Col) ?? DBNull.Value;
                    cmd.Parameters["@sp"].Value = (object)SafeCol(cols, spCol) ?? DBNull.Value;
                    cmd.ExecuteNonQuery();
                    totalRows++;
                }
            }
        }
    }
    return totalRows;
}

static string SafeCol(string[] cols, int idx)
{
    if (idx < 0 || idx >= cols.Length) return null;
    string v = cols[idx].Trim();
    return string.IsNullOrEmpty(v) ? null : v;
}

void ETLLogInicio(string connStr, string runId, string fase, string passo)
{
    try
    {
        using (var conn = new SqlConnection(connStr))
        {
            conn.Open();
            using (var cmd = new SqlCommand("dbo.sp_ETL_LogInicio", conn))
            {
                cmd.CommandType = CommandType.StoredProcedure;
                cmd.Parameters.AddWithValue("@Execucao_Id", Guid.Parse(runId));
                cmd.Parameters.AddWithValue("@Fase", fase);
                cmd.Parameters.AddWithValue("@Passo", passo);
                cmd.ExecuteNonQuery();
            }
        }
    }
    catch { }
}

void ETLLogFim(string connStr, string runId, string fase, string passo,
    string status, int lidos, int escritos, int rejeitados, string mensagem)
{
    try
    {
        using (var conn = new SqlConnection(connStr))
        {
            conn.Open();
            using (var cmd = new SqlCommand("dbo.sp_ETL_LogFim", conn))
            {
                cmd.CommandType = CommandType.StoredProcedure;
                cmd.Parameters.AddWithValue("@Execucao_Id", Guid.Parse(runId));
                cmd.Parameters.AddWithValue("@Fase", fase);
                cmd.Parameters.AddWithValue("@Passo", passo);
                cmd.Parameters.AddWithValue("@Status", status);
                cmd.Parameters.AddWithValue("@Lidos", (object)lidos ?? DBNull.Value);
                cmd.Parameters.AddWithValue("@Escritos", (object)escritos ?? DBNull.Value);
                cmd.Parameters.AddWithValue("@Rejeitados", (object)rejeitados ?? DBNull.Value);
                cmd.Parameters.AddWithValue("@Mensagem", (object)mensagem ?? DBNull.Value);
                cmd.ExecuteNonQuery();
            }
        }
    }
    catch { }
}

void ETLLogErro(string connStr, string runId, string fase, string passo,
    int erroNumero, string erroMensagem, int erroSeveridade)
{
    try
    {
        using (var conn = new SqlConnection(connStr))
        {
            conn.Open();
            using (var cmd = new SqlCommand("dbo.sp_ETL_RegistarErro", conn))
            {
                cmd.CommandType = CommandType.StoredProcedure;
                cmd.Parameters.AddWithValue("@Execucao_Id", Guid.Parse(runId));
                cmd.Parameters.AddWithValue("@Fase", fase);
                cmd.Parameters.AddWithValue("@Passo", passo);
                cmd.Parameters.AddWithValue("@Erro_Numero", (object)erroNumero ?? DBNull.Value);
                cmd.Parameters.AddWithValue("@Erro_Mensagem", (object)erroMensagem ?? DBNull.Value);
                cmd.Parameters.AddWithValue("@Erro_Severidade", (object)erroSeveridade ?? DBNull.Value);
                cmd.ExecuteNonQuery();
            }
        }
    }
    catch { }
}

enum ScriptResults { Success = 0, Failure = 1, Completion = 2 }
