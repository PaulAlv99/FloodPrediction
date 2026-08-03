using System;
using System.Data;
using System.IO;
using System.Net;
using System.Text;
using System.Data.SqlClient;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Microsoft.SqlServer.Dts.Runtime;

public void Main()
{
    Guid runGuid = Guid.NewGuid();
    string runId = runGuid.ToString();
    string connStr = "Server=localhost;Database=PreFlood_DW;Trusted_Connection=yes;";
    string landingDir = @"C:\ProjetoDW\V4\Landing";
    string urlObs = "https://api.ipma.pt/open-data/observation/meteorology/stations/observations.json";
    string urlEst = "https://api.ipma.pt/open-data/observation/meteorology/stations/stations.json";

    Dts.Variables["User::RunId"].Value = runId;

    bool fireAgain = true;

    try
    {
        string ipmaDir = Path.Combine(landingDir, "IPMA");
        Directory.CreateDirectory(ipmaDir);
        string timestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
        string runDir = Path.Combine(ipmaDir, timestamp);
        Directory.CreateDirectory(runDir);

        ETLLogInicio(connStr, runGuid, "EXTRACAO", "API->Bronze IPMA");

        Dts.Events.FireInformation(0, "ST_BronzeIPMA",
            string.Format("Starting Bronze download. RunId={0}", runId), "", 0, ref fireAgain);

        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;

        string obsFile = Path.Combine(runDir, "observations.json");
        string estFile = Path.Combine(runDir, "stations.json");
        string obsJson, estJson;

        using (var client = new WebClient { Encoding = Encoding.UTF8 })
        {
            Dts.Events.FireInformation(0, "ST_BronzeIPMA",
                "Downloading observations from " + urlObs, "", 0, ref fireAgain);
            obsJson = client.DownloadString(urlObs);
            File.WriteAllText(obsFile, obsJson, Encoding.UTF8);

            Dts.Events.FireInformation(0, "ST_BronzeIPMA",
                "Downloading stations from " + urlEst, "", 0, ref fireAgain);
            estJson = client.DownloadString(urlEst);
            File.WriteAllText(estFile, estJson, Encoding.UTF8);
        }

        int totalRows = 0;
        using (var conn = new SqlConnection(connStr))
        {
            conn.Open();
            using (var tx = conn.BeginTransaction())
            {
                try
                {
                    int estRows = InsertEstacoes(conn, tx, estJson, estFile, runGuid, ref fireAgain);
                    int obsRows = InsertObservacoes(conn, tx, obsJson, obsFile, runGuid, ref fireAgain);
                    totalRows = estRows + obsRows;
                    tx.Commit();
                }
                catch
                {
                    tx.Rollback();
                    throw;
                }
            }
        }

        Dts.Variables["User::RowCount"].Value = totalRows;
        ETLLogFim(connStr, runGuid, "EXTRACAO", "API->Bronze IPMA", "OK", totalRows, totalRows, 0, null);

        Dts.Events.FireInformation(0, "ST_BronzeIPMA",
            string.Format("Bronze complete. Total rows: {0}", totalRows), "", 0, ref fireAgain);

        Dts.TaskResult = (int)ScriptResults.Success;
    }
    catch (Exception ex)
    {
        Dts.Variables["User::ErrorMsg"].Value = ex.Message;
        ETLLogErro(connStr, runGuid, "EXTRACAO", "API->Bronze IPMA", 0, ex.Message, 0);
        Dts.Events.FireError(0, "ST_BronzeIPMA", ex.Message, "", 0);
        Dts.TaskResult = (int)ScriptResults.Failure;
    }
}

int InsertEstacoes(SqlConnection conn, SqlTransaction tx,
    string estJson, string arquivo, Guid runGuid, ref bool fireAgain)
{
    int count = 0;
    int skipped = 0;

    JArray features;
    try
    {
        features = JArray.Parse(estJson);
    }
    catch (JsonException jex)
    {
        Dts.Events.FireWarning(0, "ST_BronzeIPMA",
            "Stations JSON parse error: " + jex.Message, "", 0);
        return 0;
    }

    using (var cmd = new SqlCommand(
        @"INSERT INTO brz.ipma_est
            (id_estacao, nome, longitude, latitude, _arquivo, _run_id)
          VALUES
            (@id, @nome, @lon, @lat, @arquivo, @runId)", conn, tx))
    {
        cmd.Parameters.Add("@id", SqlDbType.NVarChar, 20);
        cmd.Parameters.Add("@nome", SqlDbType.NVarChar, 200);
        cmd.Parameters.Add("@lon", SqlDbType.NVarChar, 30);
        cmd.Parameters.Add("@lat", SqlDbType.NVarChar, 30);
        cmd.Parameters.Add("@arquivo", SqlDbType.NVarChar, 500).Value = arquivo;
        cmd.Parameters.Add("@runId", SqlDbType.UniqueIdentifier).Value = runGuid;

        foreach (JToken feature in features)
        {
            JToken props = feature["properties"];
            JToken geom = feature["geometry"];
            JToken coords = geom?["coordinates"];

            if (props == null || coords == null)
            {
                skipped++;
                continue;
            }

            string id = props["idEstacao"]?.ToString();
            string nome = props["localEstacao"]?.ToString();
            string lon = coords[0]?.ToString();
            string lat = coords[1]?.ToString();

            if (string.IsNullOrEmpty(id))
            {
                skipped++;
                continue;
            }

            cmd.Parameters["@id"].Value = id;
            cmd.Parameters["@nome"].Value = (object)nome ?? DBNull.Value;
            cmd.Parameters["@lon"].Value = (object)lon ?? DBNull.Value;
            cmd.Parameters["@lat"].Value = (object)lat ?? DBNull.Value;
            cmd.ExecuteNonQuery();
            count++;
        }
    }

    Dts.Events.FireInformation(0, "ST_BronzeIPMA",
        string.Format("Stations: inserted={0}, skipped={1}", count, skipped),
        "", 0, ref fireAgain);

    return count;
}

int InsertObservacoes(SqlConnection conn, SqlTransaction tx,
    string obsJson, string arquivo, Guid runGuid, ref bool fireAgain)
{
    int count = 0;
    int skipped = 0;

    JObject root;
    try
    {
        root = JObject.Parse(obsJson);
    }
    catch (JsonException jex)
    {
        Dts.Events.FireWarning(0, "ST_BronzeIPMA",
            "Observations JSON parse error: " + jex.Message, "", 0);
        return 0;
    }

    using (var cmd = new SqlCommand(
        @"INSERT INTO brz.ipma_obs
            (data_hora, id_estacao, temperatura, humidade, pressao,
             vento_km, vento_ms, vento_dir, precipitacao, radiacao,
             _arquivo, _run_id)
          VALUES
            (@dt, @id, @temp, @humi, @press,
             @vkm, @vms, @vdir, @prec, @rad,
             @arquivo, @runId)", conn, tx))
    {
        cmd.Parameters.Add("@dt", SqlDbType.NVarChar, 30);
        cmd.Parameters.Add("@id", SqlDbType.NVarChar, 20);
        cmd.Parameters.Add("@temp", SqlDbType.NVarChar, 20);
        cmd.Parameters.Add("@humi", SqlDbType.NVarChar, 20);
        cmd.Parameters.Add("@press", SqlDbType.NVarChar, 20);
        cmd.Parameters.Add("@vkm", SqlDbType.NVarChar, 20);
        cmd.Parameters.Add("@vms", SqlDbType.NVarChar, 20);
        cmd.Parameters.Add("@vdir", SqlDbType.NVarChar, 20);
        cmd.Parameters.Add("@prec", SqlDbType.NVarChar, 20);
        cmd.Parameters.Add("@rad", SqlDbType.NVarChar, 20);
        cmd.Parameters.Add("@arquivo", SqlDbType.NVarChar, 500).Value = arquivo;
        cmd.Parameters.Add("@runId", SqlDbType.UniqueIdentifier).Value = runGuid;

        foreach (JProperty tsKv in root.Properties())
        {
            string tsName = tsKv.Name;

            JObject stations = tsKv.Value as JObject;
            if (stations == null) { skipped++; continue; }

            foreach (JProperty stKv in stations.Properties())
            {
                JObject fields = stKv.Value as JObject;
                if (fields == null) { skipped++; continue; }

                cmd.Parameters["@dt"].Value = tsName;
                cmd.Parameters["@id"].Value = stKv.Name;
                cmd.Parameters["@temp"].Value = GetStr(fields, "temperatura");
                cmd.Parameters["@humi"].Value = GetStr(fields, "humidade");
                cmd.Parameters["@press"].Value = GetStr(fields, "pressao");
                cmd.Parameters["@vkm"].Value = GetStr(fields, "intensidadeVentoKM");
                cmd.Parameters["@vms"].Value = GetStr(fields, "intensidadeVento");
                cmd.Parameters["@vdir"].Value = GetStr(fields, "idDireccVento");
                cmd.Parameters["@prec"].Value = GetStr(fields, "precAcumulada");
                cmd.Parameters["@rad"].Value = GetStr(fields, "radiacao");

                cmd.ExecuteNonQuery();
                count++;
            }
        }
    }

    Dts.Events.FireInformation(0, "ST_BronzeIPMA",
        string.Format("Observations: inserted={0}, skipped={1}", count, skipped),
        "", 0, ref fireAgain);

    return count;
}

static string GetStr(JObject obj, string key)
{
    JToken val = obj[key];
    if (val == null || val.Type == JTokenType.Null)
        return "";
    return val.ToString();
}

void ETLLogInicio(string connStr, Guid runGuid, string fase, string passo)
{
    try
    {
        using (var conn = new SqlConnection(connStr))
        {
            conn.Open();
            using (var cmd = new SqlCommand("dbo.sp_ETL_LogInicio", conn))
            {
                cmd.CommandType = CommandType.StoredProcedure;
                cmd.Parameters.AddWithValue("@Execucao_Id", runGuid);
                cmd.Parameters.AddWithValue("@Fase", fase);
                cmd.Parameters.AddWithValue("@Passo", passo);
                cmd.ExecuteNonQuery();
            }
        }
    }
    catch { }
}

void ETLLogFim(string connStr, Guid runGuid, string fase, string passo,
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
                cmd.Parameters.AddWithValue("@Execucao_Id", runGuid);
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

void ETLLogErro(string connStr, Guid runGuid, string fase, string passo,
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
                cmd.Parameters.AddWithValue("@Execucao_Id", runGuid);
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

enum ScriptResults
{
    Success = 0,
    Failure = 1,
    Completion = 2
}
