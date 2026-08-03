using System;
using System.Collections;
using System.Collections.Generic;
using System.Data;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml;
using System.Data.SqlClient;
using Microsoft.SqlServer.Dts.Runtime;

const string BASE_URL = "https://snirh.apambiente.pt";
const string INDEX_URL = BASE_URL + "/index.php?idMain=2&idItem=1";
const string XML_URL = BASE_URL + "/snirh/_dadosbase/site/xml/xml_listaestacoes.php";
const string DATA_URL = BASE_URL + "/snirh/_dadosbase/site/paraCSV/dados_csv.php";
const string TIPO_HIDRO = "920123705";

Dictionary<string, string> ParamMap = new Dictionary<string, string>
{
    { "1850",       "CAUDAL MEDIO DIARIO" },
    { "1845",       "NIVEL MEDIO DIARIO" },
    { "1843",       "NIVEL HIDROMETRICO INSTANTANEO" },
    { "3212219030", "CAUDAL TRANSFERIDO HORARIO" },
    { "354895424",  "COTA DA ALBUFEIRA NA ULTIMA HORA" }
};

public void Main()
{
    string runId = Guid.NewGuid().ToString();
    string connStr = "Server=localhost;Database=PreFlood_DW;Trusted_Connection=yes;";
    string landingDir = @"C:\ProjetoDW\V4\Landing";
    string bacia = "47";
    string paramIds = "1850,1845,1843,3212219030,354895424";

    Dts.Variables["User::RunId"].Value = runId;

    ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;

    DateTime startTime = DateTime.Now;
    ETLLogInicio(connStr, runId, "EXTRACAO", "API->Bronze SNIRH");
    try
    {
        string snirhDir = Path.Combine(landingDir, "SNIRH");
        Directory.CreateDirectory(snirhDir);
        string timestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
        string runDir = Path.Combine(snirhDir, timestamp);
        Directory.CreateDirectory(runDir);

        bool fireAgain = true;
        Dts.Events.FireInformation(0, "ST_BronzeSNIRH",
            string.Format("Starting Bronze download. RunId={0} Bacia={1}", runId, bacia), "", 0, ref fireAgain);

        var handler = new HttpClientHandler
        {
            CookieContainer = new CookieContainer(),
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate
        };
        using (var client = new HttpClient(handler))
        {
            client.Timeout = TimeSpan.FromSeconds(120);
            client.DefaultRequestHeaders.Add("User-Agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0");
            client.DefaultRequestHeaders.Add("Accept-Language", "en-US,en;q=0.9");

            InitSession(client);

            var estacoes = ObterEstacoes(client, bacia, runDir);
            Dts.Events.FireInformation(0, "ST_BronzeSNIRH",
                string.Format("Found {0} stations", estacoes.Count), "", 0, ref fireAgain);

            if (estacoes.Count == 0)
            {
                Dts.Events.FireWarning(0, "ST_BronzeSNIRH",
                    "No stations found. SNIRH session may not have initialized.", "", 0);
            }

            int totalRows = 0;
            using (var conn = new SqlConnection(connStr))
            {
                conn.Open();
                using (var tx = conn.BeginTransaction())
                {
                    try
                    {
                        int estRows = InsertEstacoes(conn, tx, estacoes, Path.Combine(runDir, "estacoes.xml"), runId);
                        Dts.Events.FireInformation(0, "ST_BronzeSNIRH",
                            string.Format("Inserted {0} stations", estRows), "", 0, ref fireAgain);

                        int csvCount = DownloadCSVs(client, conn, tx, estacoes, paramIds, runDir, timestamp, runId);
                        totalRows = estRows + csvCount;
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
            ETLLogFim(connStr, runId, "EXTRACAO", "API->Bronze SNIRH", "OK", totalRows, totalRows, 0, null);
            Dts.Events.FireInformation(0, "ST_BronzeSNIRH",
                string.Format("Bronze complete. Total rows: {0}", totalRows), "", 0, ref fireAgain);
            Dts.TaskResult = (int)ScriptResults.Success;
        }
    }
    catch (Exception ex)
    {
        string msg = ex.Message;
        if (ex is AggregateException aex)
        {
            msg = "AggregateException:";
            foreach (var ie in aex.InnerExceptions)
                msg += " " + ie.Message;
            if (aex.InnerException != null && aex.InnerException.InnerException != null)
                msg += " | Inner: " + aex.InnerException.InnerException.Message;
        }
        Dts.Variables["User::ErrorMsg"].Value = msg;
        ETLLogErro(connStr, runId, "EXTRACAO", "API->Bronze SNIRH", 0, msg, 0);
        Dts.Events.FireError(0, "ST_BronzeSNIRH", msg, "", 0);
        Dts.TaskResult = (int)ScriptResults.Failure;
    }
}

void InitSession(HttpClient client)
{
    var payload = new Dictionary<string, string>
    {
        { "FILTRA_BACIA", "" },
        { "FILTRA_COVER", "" },
        { "FILTRA_SITE", "" },
        { "f_redes_seleccao[]", TIPO_HIDRO },
        { "aplicar_filtro", "1" },
        { "f_data_c", "30" }
    };

    try
    {
        bool fire = true;
        Dts.Events.FireInformation(0, "ST_BronzeSNIRH",
            "InitSession: sending minimal POST to establish cookies...", "", 0, ref fire);

        var content = new FormUrlEncodedContent(payload);
        var postTask = client.PostAsync(INDEX_URL, content);
        postTask.Wait();
        var resp = postTask.Result;

        Dts.Events.FireInformation(0, "ST_BronzeSNIRH",
            string.Format("InitSession: HTTP {0}", (int)resp.StatusCode), "", 0, ref fire);
    }
    catch (AggregateException aex)
    {
        string msg = aex.InnerException != null ? aex.InnerException.Message : aex.Message;
        Dts.Events.FireWarning(0, "ST_BronzeSNIRH",
            string.Format("InitSession failed (non-fatal): {0}", msg), "", 0);
    }
}

List<Dictionary<string, string>> ObterEstacoes(HttpClient client, string bacia, string runDir)
{
    var estacoes = new List<Dictionary<string, string>>();

    var payload = new Dictionary<string, string>
    {
        { "FILTRA_BACIA", "" },
        { "FILTRA_COVER", "" },
        { "FILTRA_SITE", "" },
        { "click_x", "" },
        { "click_y", "" },
        { "zf", "" },
        { "movemapa", "" },
        { "gmaps_centro_latitude", "39.6936944" },
        { "gmaps_centro_longitude", "-8.131475" },
        { "gmaps_centro_zoom", "7" },
        { "validar_lista_estacoes", "" },
        { "f_seleccao_data_tmin", "20/07/1957" },
        { "f_seleccao_data_tmax", DateTime.Now.ToString("dd/MM/yyyy") },
        { "f_calcular_tmin_tmax", "" },
        { "nconjuntos_max_variavel", "50" },
        { "f_temas_mapa_altimetria", "1" },
        { "f_temas_mapa_gbacias", "1" },
        { "f_raio_simbolo_mapa", "5" },
        { "f_simbolo_estacao", "1" },
        { "f_listar_estacoes_offmapa", "2" },
        { "f_cor_rede1", "#0099FF" },
        { "f_cor_rede2", "#009900" },
        { "f_cor_rede3", "#999999" },
        { "f_cor_rede4", "#CCFF00" },
        { "f_tipo_de_mapa", "2" },
        { "f_redes_seleccao[]", TIPO_HIDRO },
        { "f_data_a", "" },
        { "f_data_b", "" },
        { "f_data_c", "30" },
        { "f_data_anos", "" },
        { "f_valores_superior_a", "" },
        { "f_valores_inferior_a", "" },
        { "f_estacao_like", "" },
        { "f_simbolo_like", "" },
        { "f_simbolo_in", "" },
        { "f_estado", "" },
        { "f_curso_agua", "" },
        { "f_divisao_administrativa", "" },
        { "f_altitude", "" },
        { "f_area_drenada", "" },
        { "f_login_password", "" },
        { "aplicar_filtro", "1" },
        { "aplicar_filtro_dados", "" },
        { "f_baciash_seleccao[]", bacia }
    };

    try
    {
        bool fire = true;

        Dts.Events.FireInformation(0, "ST_BronzeSNIRH",
            "ObterEstacoes: sending full warmup POST...", "", 0, ref fire);

        var warmupContent = new FormUrlEncodedContent(payload);
        var warmupTask = client.PostAsync(INDEX_URL, warmupContent);
        warmupTask.Wait();
        var warmupResp = warmupTask.Result;

        Dts.Events.FireInformation(0, "ST_BronzeSNIRH",
            string.Format("ObterEstacoes warmup: HTTP {0}", (int)warmupResp.StatusCode), "", 0, ref fire);

        Dts.Events.FireInformation(0, "ST_BronzeSNIRH",
            "ObterEstacoes: fetching stations XML...", "", 0, ref fire);

        var req = new HttpRequestMessage(HttpMethod.Get, XML_URL);
        req.Headers.Add("X-Requested-With", "XMLHttpRequest");
        req.Headers.Referrer = new Uri(BASE_URL + "/");
        var respTask = client.SendAsync(req);
        respTask.Wait();
        var resp = respTask.Result;

        Dts.Events.FireInformation(0, "ST_BronzeSNIRH",
            string.Format("Stations XML: HTTP {0}", (int)resp.StatusCode), "", 0, ref fire);

        resp.EnsureSuccessStatusCode();

        var readTask = resp.Content.ReadAsStringAsync();
        readTask.Wait();
        string xml = readTask.Result;

        if (string.IsNullOrWhiteSpace(xml))
        {
            Dts.Events.FireWarning(0, "ST_BronzeSNIRH",
                "Empty XML response. Session may have expired.", "", 0);
            return estacoes;
        }

        File.WriteAllText(Path.Combine(runDir, "estacoes.xml"), xml, Encoding.UTF8);

        if (!xml.TrimStart().StartsWith("<"))
        {
            Dts.Events.FireWarning(0, "ST_BronzeSNIRH",
                "Response is not XML. First 200 chars: " + xml.Substring(0, Math.Min(xml.Length, 200)), "", 0);
            return estacoes;
        }

        var doc = new XmlDocument();
        doc.LoadXml(xml);

        foreach (XmlNode marker in doc.SelectNodes("//marker"))
        {
            var est = new Dictionary<string, string>();
            est["id"] = marker.Attributes["site"] != null ? marker.Attributes["site"].Value : "";
            string nome = marker.Attributes["estacao"] != null ? marker.Attributes["estacao"].Value : "";
            nome = WebUtility.HtmlDecode(nome).Replace("\u25A0", "").Replace("\u00A0", " ").Trim();
            est["nome"] = nome;
            est["lat"] = marker.Attributes["lat"] != null ? marker.Attributes["lat"].Value : "";
            est["lng"] = marker.Attributes["lng"] != null ? marker.Attributes["lng"].Value : "";
            est["activa"] = (marker.Attributes["activa"] != null && marker.Attributes["activa"].Value == "1") ? "1" : "0";
            estacoes.Add(est);
        }

        Dts.Events.FireInformation(0, "ST_BronzeSNIRH",
            string.Format("Parsed {0} stations from XML", estacoes.Count), "", 0, ref fire);
    }
    catch (AggregateException aex)
    {
        string msg = aex.InnerException != null ? aex.InnerException.Message : aex.Message;
        if (aex.InnerException != null && aex.InnerException.InnerException != null)
            msg += " | " + aex.InnerException.InnerException.Message;
        Dts.Events.FireError(0, "ST_BronzeSNIRH",
            string.Format("ObterEstacoes failed: {0}", msg), "", 0);
        throw;
    }
    catch (Exception ex)
    {
        Dts.Events.FireError(0, "ST_BronzeSNIRH",
            string.Format("ObterEstacoes failed: {0}", ex.Message), "", 0);
        throw;
    }

    return estacoes;
}

int InsertEstacoes(SqlConnection conn, SqlTransaction tx, List<Dictionary<string, string>> estacoes, string arquivo, string runId)
{
    int count = 0;
    foreach (var est in estacoes)
    {
        using (var cmd = new SqlCommand(
            @"INSERT INTO brz.snirh_est (id_estacao, nome, latitude, longitude, activa, _arquivo, _run_id)
              VALUES (@id, @nome, @lat, @lon, @activa, @arquivo, @runId)", conn, tx))
        {
            cmd.Parameters.AddWithValue("@id", est["id"]);
            cmd.Parameters.AddWithValue("@nome", est["nome"]);
            cmd.Parameters.AddWithValue("@lat", (object)est["lat"] ?? DBNull.Value);
            cmd.Parameters.AddWithValue("@lon", (object)est["lng"] ?? DBNull.Value);
            cmd.Parameters.AddWithValue("@activa", est["activa"]);
            cmd.Parameters.AddWithValue("@arquivo", arquivo);
            cmd.Parameters.AddWithValue("@runId", Guid.Parse(runId));
            cmd.ExecuteNonQuery();
        }
        count++;
    }
    return count;
}

int DownloadCSVs(HttpClient client, SqlConnection conn, SqlTransaction tx,
    List<Dictionary<string, string>> estacoes, string paramIds,
    string runDir, string timestamp, string runId)
{
    int totalRows = 0;
    DateTime dataFim = DateTime.Now;
    DateTime dataInicio = dataFim.AddYears(-16);
    string dtInicio = dataInicio.ToString("dd/MM/yyyy");
    string dtFim = dataFim.ToString("dd/MM/yyyy");
    string[] pIds = paramIds.Split(',');

    using (var insCmd = new SqlCommand(
        @"INSERT INTO brz.snirh_obs (data_hora, id_estacao, id_parametro, valor, _arquivo, _run_id)
          VALUES (@dt, @est, @param, @val, @arquivo, @runId)", conn, tx))
    {
        insCmd.Parameters.Add("@dt", SqlDbType.NVarChar, 30);
        insCmd.Parameters.Add("@est", SqlDbType.NVarChar, 20);
        insCmd.Parameters.Add("@param", SqlDbType.NVarChar, 20);
        insCmd.Parameters.Add("@val", SqlDbType.NVarChar, 30);
        insCmd.Parameters.Add("@arquivo", SqlDbType.NVarChar, 500);
        insCmd.Parameters.Add("@runId", SqlDbType.UniqueIdentifier);
        insCmd.Parameters["@runId"].Value = Guid.Parse(runId);

        int stationIdx = 0;
        foreach (var est in estacoes)
        {
            stationIdx++;
            string estId = est["id"];
            string estNome = Sanitize(est["nome"]);
            string csvFile = Path.Combine(runDir, string.Format("snirh_{0}_{1}_{2}.csv", estNome, estId, timestamp));
            try
            {
                string url = string.Format("{0}?sites={1}&pars={2}&tmin={3}&tmax={4}&formato=csv",
                    DATA_URL,
                    estId,
                    Uri.EscapeDataString(string.Join(",", pIds)),
                    Uri.EscapeDataString(dtInicio),
                    Uri.EscapeDataString(dtFim));

                var csvReq = new HttpRequestMessage(HttpMethod.Get, url);
                csvReq.Headers.Add("X-Requested-With", "XMLHttpRequest");
                csvReq.Headers.Referrer = new Uri(INDEX_URL);

                var csvTask = client.SendAsync(csvReq);
                csvTask.Wait();
                var csvResp = csvTask.Result;

                var bytesTask = csvResp.Content.ReadAsByteArrayAsync();
                bytesTask.Wait();
                byte[] csvBytes = bytesTask.Result;

                if (csvBytes == null || csvBytes.Length == 0)
                {
                    Dts.Events.FireWarning(0, "ST_BronzeSNIRH",
                        string.Format("Station {0}/{1} [{2}]: empty CSV (session expired?)", stationIdx, estacoes.Count, estId), "", 0);
                    continue;
                }

                string cleanedCsv = StripSnirhHeaders(csvBytes);
                if (string.IsNullOrWhiteSpace(cleanedCsv))
                {
                    Dts.Events.FireWarning(0, "ST_BronzeSNIRH",
                        string.Format("Station {0}/{1} [{2}]: no data rows", stationIdx, estacoes.Count, estId), "", 0);
                    continue;
                }

                File.WriteAllText(csvFile, cleanedCsv, Encoding.GetEncoding(28591));
                int rows = ParseCSV(insCmd, csvFile, estId);
                totalRows += rows;

                if (rows > 0)
                {
                    bool f = true;
                    Dts.Events.FireInformation(0, "ST_BronzeSNIRH",
                        string.Format("Station {0}/{1} [{2}]: {3} obs rows", stationIdx, estacoes.Count, estId, rows), "", 0, ref f);
                }
            }
            catch (Exception ex)
            {
                Dts.Events.FireWarning(0, "ST_BronzeSNIRH",
                    string.Format("Station {0}/{1} [{2}] failed: {3}", stationIdx, estacoes.Count, estId, ex.Message), "", 0);
            }
        }
    }
    return totalRows;
}

int ParseCSV(SqlCommand cmd, string csvFile, string estacaoId)
{
    int count = 0;
    string[] lines = File.ReadAllLines(csvFile, Encoding.GetEncoding(28591));
    if (lines.Length < 3) return 0;

    string[] headerRow1 = lines[0].Split(',');
    string[] headerRow2 = lines[1].Split(',');

    int[] paramColMap = new int[headerRow2.Length];
    string[] paramIdMap = new string[headerRow2.Length];

    int dateCol = -1;
    for (int i = 0; i < headerRow1.Length; i++)
    {
        string h1 = headerRow1[i].Trim().ToUpperInvariant();
        if (h1.Contains("DATA") || h1.Contains("DATE"))
        {
            dateCol = i;
            break;
        }
    }
    if (dateCol < 0) dateCol = 0;

    for (int i = 0; i < headerRow2.Length; i++)
    {
        string h2 = headerRow2[i].Trim().ToUpperInvariant();
        if (h2 == "FLAG" || string.IsNullOrEmpty(h2))
        {
            paramIdMap[i] = null;
            continue;
        }
        if (i == dateCol)
        {
            paramIdMap[i] = null;
            continue;
        }
        paramIdMap[i] = ResolveParamId(h2);
    }

    for (int r = 2; r < lines.Length; r++)
    {
        string line = lines[r].Trim();
        if (string.IsNullOrEmpty(line)) continue;
        string[] cols = line.Split(',');
        if (cols.Length < 2 || dateCol >= cols.Length) continue;
        string dataStr = cols[dateCol].Trim();
        if (string.IsNullOrEmpty(dataStr)) continue;
        DateTime obsDate;
        if (!DateTime.TryParseExact(dataStr,
            new[] { "dd/MM/yyyy HH:mm", "dd/MM/yyyy", "yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd" },
            CultureInfo.InvariantCulture, DateTimeStyles.None, out obsDate)) continue;

        for (int c = 0; c < cols.Length; c++)
        {
            if (c == dateCol) continue;
            if (c >= paramIdMap.Length || paramIdMap[c] == null) continue;
            string val = cols[c].Trim();
            if (string.IsNullOrEmpty(val) || val == "-" || val.StartsWith("(")) continue;

            cmd.Parameters["@dt"].Value = obsDate.ToString("yyyy-MM-dd HH:mm:ss");
            cmd.Parameters["@est"].Value = estacaoId;
            cmd.Parameters["@param"].Value = paramIdMap[c];
            cmd.Parameters["@val"].Value = val;
            cmd.Parameters["@arquivo"].Value = csvFile;
            cmd.ExecuteNonQuery();
            count++;
        }
    }
    return count;
}

string ResolveParamId(string header)
{
    string h = RemoveDiacritics(header.ToUpperInvariant());
    foreach (var kvp in ParamMap)
    {
        if (h.Contains(RemoveDiacritics(kvp.Value.ToUpperInvariant())))
            return kvp.Key;
    }
    return null;
}

string RemoveDiacritics(string text)
{
    if (string.IsNullOrEmpty(text)) return text;
    var sb = new StringBuilder();
    foreach (char c in text.Normalize(NormalizationForm.FormD))
    {
        if (CharUnicodeInfo.GetUnicodeCategory(c) != UnicodeCategory.NonSpacingMark)
            sb.Append(c);
    }
    return sb.ToString();
}

string StripSnirhHeaders(byte[] raw)
{
    string text = Encoding.GetEncoding(28591).GetString(raw);
    var lines = text.Split(new[] { "\r\n", "\n" }, StringSplitOptions.None);
    var output = new List<string>();
    int headerCount = 0;
    foreach (string line in lines)
    {
        string s = line.Trim();
        if (string.IsNullOrEmpty(s)) continue;

        if (headerCount < 2)
        {
            if ((s.Contains(";") || s.Contains(","))
                && s.Length > 10
                && !s.ToLowerInvariant().StartsWith("snirh")
                && !s.ToLowerInvariant().StartsWith("dados obtidos")
                && !s.StartsWith("http")
                && !s.StartsWith("FILTRA_")
                && !s.StartsWith("f_")
                && !(s.Length > 20 && s.IndexOf('=') >= 0 && s.IndexOf('=') < 20))
            {
                output.Add(line);
                headerCount++;
            }
        }
        else
        {
            output.Add(line);
        }
    }
    return string.Join("\r\n", output);
}

string Sanitize(string name)
{
    foreach (char c in Path.GetInvalidFileNameChars()) name = name.Replace(c, '_');
    return name.Length > 60 ? name.Substring(0, 60) : name;
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
