package com.wanxiangupdater

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.ui.draw.clip
import androidx.documentfile.provider.DocumentFile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL
import java.util.UUID
import java.util.zip.ZipFile
import java.util.zip.ZipInputStream

val MorandiGreen = Color(0xFF61A165)
val MorandiDarkGreen = Color(0xFF49814D)
val MorandiLightGreen = Color(0xFFF0F5F1)
val MorandiBorder = Color(0xFFA8C7AA)

val DEFAULT_EXCLUDE_RULES = listOf(
    """^custom_phrase\.txt$""",
    """.*userdb$""",
    """.*userdb\.txt""",
    """sequence.*txt""",
    """^(?!custom/).*\.custom\.yaml$""",
    """^user\.yaml$""",
    """^installation\.yaml$""",
    """^sync/.*"""
).joinToString("\n")

const val OFFICIAL_ROUTE_ID = "official"
const val GITHUB_ROUTE_TEST_URL = "https://github.com/amzxyz/rime-wanxiang/releases/download/dict-nightly/base-dicts.zip"
const val DEFAULT_MIN_PROXY_SPEED_KBPS = 64
const val LOW_SPEED_GRACE_MS = 8_000L
const val LOW_SPEED_WINDOW_MS = 3_000L

class LowSpeedFallbackException(val speedKbps: Long) : Exception("代理速度过低：${speedKbps}KB/s")

data class GithubRoute(val id: String, val name: String, val prefix: String)
data class RouteProbe(val ok: Boolean, val latencyMs: Long = Long.MAX_VALUE, val error: String = "")
data class DownloadCandidate(val url: String, val name: String, val usesProxy: Boolean = false, val isCnb: Boolean = false)

val DEFAULT_GITHUB_ROUTES = listOf(
    GithubRoute(OFFICIAL_ROUTE_ID, "GitHub", ""),
    GithubRoute("b52m", "gh.b52m.cn", "https://gh.b52m.cn/"),
    GithubRoute("gh-proxy-com", "gh-proxy.com", "https://gh-proxy.com/"),
    GithubRoute("ghfast-top", "ghfast.top", "https://ghfast.top/"),
    GithubRoute("xxlab", "xxlab", "https://github.xxlab.tech/"),
    GithubRoute("xxooo", "xxooo", "https://gh.xxooo.cf/")
)

class TaskState(val title: String, val url: String, val cnbFallbackUrl: String? = null) {
    var progress by mutableStateOf(0f)
    var status by mutableStateOf("等待中...")
    var isFinished by mutableStateOf(false)
    var isError by mutableStateOf(false)
}

fun normalizeProxyPrefix(value: String): String? {
    val text = value.trim()
    if (!text.startsWith("https://") && !text.startsWith("http://")) return null
    return text.trimEnd('/') + "/"
}

fun loadGithubRoutes(sharedPref: android.content.SharedPreferences): List<GithubRoute> {
    val raw = sharedPref.getString("github_routes_json", null) ?: return DEFAULT_GITHUB_ROUTES

    return try {
        val array = org.json.JSONArray(raw)
        val routes = mutableListOf<GithubRoute>()

        for (i in 0 until array.length()) {
            val obj = array.optJSONObject(i) ?: continue
            val id = obj.optString("id").trim()
            val name = obj.optString("name").trim()
            val prefix = obj.optString("prefix").trim()

            if (id.isBlank() || name.isBlank()) continue
            if (id != OFFICIAL_ROUTE_ID && normalizeProxyPrefix(prefix) == null) continue

            routes.add(GithubRoute(id, name, if (id == OFFICIAL_ROUTE_ID) "" else normalizeProxyPrefix(prefix)!!))
        }

        val withoutDuplicatePrefix = routes.distinctBy { it.prefix }
        if (withoutDuplicatePrefix.none { it.id == OFFICIAL_ROUTE_ID }) {
            listOf(DEFAULT_GITHUB_ROUTES.first()) + withoutDuplicatePrefix
        } else {
            withoutDuplicatePrefix
        }
    } catch (_: Exception) {
        DEFAULT_GITHUB_ROUTES
    }
}

fun saveGithubRoutes(routes: List<GithubRoute>, sharedPref: android.content.SharedPreferences) {
    val array = org.json.JSONArray()
    routes.forEach { route ->
        array.put(org.json.JSONObject().apply {
            put("id", route.id)
            put("name", route.name)
            put("prefix", route.prefix)
        })
    }
    sharedPref.edit().putString("github_routes_json", array.toString()).apply()
}

const val DEPLOY_PATHS_JSON_KEY = "deploy_paths_json"

fun saveDeployPaths(paths: List<String>, sharedPref: android.content.SharedPreferences) {
    val normalized = paths.map { it.trim() }.filter { it.isNotBlank() }.distinct()
    val array = org.json.JSONArray()
    normalized.forEach { array.put(it) }

    sharedPref.edit()
        .putString(DEPLOY_PATHS_JSON_KEY, array.toString())
        .remove("deploy_paths")
        .apply()
}

fun loadDeployPaths(sharedPref: android.content.SharedPreferences): List<String> {
    val json = sharedPref.getString(DEPLOY_PATHS_JSON_KEY, null)

    if (!json.isNullOrBlank()) {
        try {
            val array = org.json.JSONArray(json)
            val paths = buildList {
                for (i in 0 until array.length()) {
                    val path = array.optString(i).trim()
                    if (path.isNotBlank() && path !in this) add(path)
                }
            }
            if (paths.isNotEmpty()) return paths
        } catch (_: Exception) {
        }
    }

    // 兼容旧版 StringSet。旧集合没有稳定顺序，迁移时把 SAF 放前面、/rime 放最后。
    val legacyPaths = sharedPref.getStringSet("deploy_paths", null)
        ?.map { it.trim() }
        ?.filter { it.isNotBlank() }
        ?.distinct()
        ?.sortedBy { if (it == "DEFAULT") 1 else 0 }
        .orEmpty()

    val migrated = if (legacyPaths.isEmpty()) listOf("DEFAULT") else legacyPaths
    saveDeployPaths(migrated, sharedPref)
    return migrated
}

fun deployPathDisplayName(path: String): String {
    if (path == "DEFAULT") return "/rime"

    return runCatching {
        Uri.decode(path)
            .substringAfterLast(":")
            .trimEnd('/')
            .substringAfterLast("/")
            .ifBlank { "SAF授权目录" }
    }.getOrDefault("SAF授权目录")
}

fun canWriteDefaultRime(): Boolean {
    return Build.VERSION.SDK_INT < Build.VERSION_CODES.R || Environment.isExternalStorageManager()
}

fun versionNumbers(value: String): List<Int> {
    return Regex("""\d+""").findAll(value).mapNotNull { it.value.toIntOrNull() }.toList()
}

fun isRemoteVersionNewer(remote: String, local: String): Boolean {
    val remoteParts = versionNumbers(remote)
    val localParts = versionNumbers(local)
    val size = maxOf(remoteParts.size, localParts.size)

    for (i in 0 until size) {
        val remotePart = remoteParts.getOrElse(i) { 0 }
        val localPart = localParts.getOrElse(i) { 0 }
        if (remotePart != localPart) return remotePart > localPart
    }
    return false
}

fun buildGithubCandidates(
    originalUrl: String,
    routes: List<GithubRoute>,
    selectedRouteId: String,
    cnbFallbackUrl: String? = null
): List<DownloadCandidate> {
    val result = mutableListOf<DownloadCandidate>()

    if (originalUrl.startsWith("https://github.com/")) {
        val official = routes.firstOrNull { it.id == OFFICIAL_ROUTE_ID } ?: DEFAULT_GITHUB_ROUTES.first()
        val proxies = routes.filter { it.prefix.isNotBlank() }
        val selected = routes.firstOrNull { it.id == selectedRouteId } ?: official

        val orderedRoutes = if (selected.prefix.isBlank()) {
            listOf(official) + proxies
        } else {
            listOf(selected) + proxies.filter { it.id != selected.id }
        }

        orderedRoutes.distinctBy { it.prefix }.forEach { route ->
            val downloadUrl = if (route.prefix.isBlank()) originalUrl else route.prefix + originalUrl
            result.add(DownloadCandidate(downloadUrl, route.name, route.prefix.isNotBlank(), false))
        }
    } else {
        val hostName = runCatching { URL(originalUrl).host }.getOrDefault("").ifBlank { "直链" }
        result.add(DownloadCandidate(originalUrl, hostName, false, originalUrl.contains("cnb.cool")))
    }

    if (!cnbFallbackUrl.isNullOrBlank()) {
        result.add(DownloadCandidate(cnbFallbackUrl, "CNB兜底", false, true))
    }

    return result.distinctBy { it.url }
}

fun buildGithubApiCandidates(apiUrl: String, routes: List<GithubRoute>, selectedRouteId: String): List<DownloadCandidate> {
    val official = routes.firstOrNull { it.id == OFFICIAL_ROUTE_ID } ?: DEFAULT_GITHUB_ROUTES.first()
    val proxies = routes.filter { it.prefix.isNotBlank() }
    val selected = routes.firstOrNull { it.id == selectedRouteId } ?: official

    val orderedRoutes = if (selected.prefix.isBlank()) {
        listOf(official) + proxies
    } else {
        listOf(selected) + proxies.filter { it.id != selected.id }
    }

    return orderedRoutes.distinctBy { it.prefix }.map { route ->
        DownloadCandidate(
            url = if (route.prefix.isBlank()) apiUrl else route.prefix + apiUrl,
            name = route.name,
            usesProxy = route.prefix.isNotBlank()
        )
    }
}

suspend fun fetchGithubApiJson(
    apiUrl: String,
    routes: List<GithubRoute>,
    selectedRouteId: String,
    token: String
): String? = withContext(Dispatchers.IO) {
    for (candidate in buildGithubApiCandidates(apiUrl, routes, selectedRouteId)) {
        var conn: HttpURLConnection? = null
        try {
            conn = URL(candidate.url).openConnection() as HttpURLConnection
            conn.instanceFollowRedirects = true
            conn.connectTimeout = 8000
            conn.readTimeout = 12000
            conn.setRequestProperty("User-Agent", "WanxiangUpdater-Android")
            conn.setRequestProperty("Accept", "application/vnd.github+json, application/json")

            if (!candidate.usesProxy && token.isNotBlank()) {
                conn.setRequestProperty("Authorization", "Bearer $token")
            }

            val code = conn.responseCode
            if (code !in 200..299) continue

            val contentType = conn.contentType.orEmpty().lowercase()
            if ("text/html" in contentType) continue

            val content = conn.inputStream.bufferedReader().use { it.readText() }.trim()
            if (content.startsWith("{") || content.startsWith("[")) return@withContext content
        } catch (_: Exception) {
        } finally {
            conn?.disconnect()
        }
    }
    null
}

suspend fun fetchCnbReleases(repo: String): org.json.JSONArray? = withContext(Dispatchers.IO) {
    var conn: HttpURLConnection? = null
    try {
        conn = URL("https://cnb.cool/amzxyz/$repo/-/releases").openConnection() as HttpURLConnection
        conn.connectTimeout = 8000
        conn.readTimeout = 12000
        conn.setRequestProperty("User-Agent", "WanxiangUpdater-Android")
        conn.setRequestProperty("Accept", "application/json")

        if (conn.responseCode !in 200..299) return@withContext null

        val content = conn.inputStream.bufferedReader().use { it.readText() }.trim()
        if (content.startsWith("[")) {
            org.json.JSONArray(content)
        } else {
            org.json.JSONObject(content).optJSONArray("releases")
        }
    } catch (_: Exception) {
        null
    } finally {
        conn?.disconnect()
    }
}

fun releaseTag(release: org.json.JSONObject): String {
    val raw = release.optString("tag_name").ifBlank { release.optString("tag_ref") }
    return raw.substringAfterLast("/")
}

fun findLatestStableCnbTag(releases: org.json.JSONArray?): String? {
    if (releases == null) return null

    val ignored = setOf("v1.0.0", "1.0.0", "dict-nightly", "model", "tool", "apk")
    var bestTag: String? = null

    for (i in 0 until releases.length()) {
        val tag = releaseTag(releases.optJSONObject(i) ?: continue)
        if (tag.isBlank() || tag.lowercase() in ignored || "model" in tag.lowercase()) continue
        if (bestTag == null || isRemoteVersionNewer(tag, bestTag!!)) bestTag = tag
    }
    return bestTag
}

fun findCnbAsset(
    releases: org.json.JSONArray?,
    wantedTag: String,
    namePredicate: (String) -> Boolean
): Pair<String, String>? {
    if (releases == null) return null

    for (i in 0 until releases.length()) {
        val release = releases.optJSONObject(i) ?: continue
        if (releaseTag(release) != wantedTag) continue

        val assets = release.optJSONArray("assets") ?: continue
        for (j in 0 until assets.length()) {
            val asset = assets.optJSONObject(j) ?: continue
            val name = asset.optString("name")
            if (!namePredicate(name)) continue

            val path = asset.optString("path")
            val browserUrl = asset.optString("browser_download_url")
            val url = when {
                path.startsWith("http") -> path
                path.isNotBlank() -> "https://cnb.cool$path"
                browserUrl.isNotBlank() -> browserUrl
                else -> ""
            }
            if (url.isNotBlank()) return name to url
        }
    }
    return null
}

suspend fun probeGithubRoute(route: GithubRoute): RouteProbe = withContext(Dispatchers.IO) {
    val testUrl = if (route.prefix.isBlank()) GITHUB_ROUTE_TEST_URL else route.prefix + GITHUB_ROUTE_TEST_URL
    var conn: HttpURLConnection? = null
    val started = System.nanoTime()

    try {
        conn = URL(testUrl).openConnection() as HttpURLConnection
        conn.instanceFollowRedirects = true
        conn.connectTimeout = 5000
        conn.readTimeout = 8000
        conn.setRequestProperty("User-Agent", "WanxiangUpdater-Android")
        conn.setRequestProperty("Range", "bytes=0-3")
        conn.setRequestProperty("Accept-Encoding", "identity")

        if (conn.responseCode !in listOf(200, 206)) {
            return@withContext RouteProbe(false, error = "HTTP ${conn.responseCode}")
        }

        if ("text/html" in conn.contentType.orEmpty().lowercase()) {
            return@withContext RouteProbe(false, error = "返回网页")
        }

        val header = ByteArray(4)
        val read = conn.inputStream.use { input ->
            var offset = 0
            while (offset < header.size) {
                val count = input.read(header, offset, header.size - offset)
                if (count < 0) break
                offset += count
            }
            offset
        }

        val isZip = read == 4 && header[0] == 'P'.code.toByte() && header[1] == 'K'.code.toByte()
        if (!isZip) return@withContext RouteProbe(false, error = "返回内容不是ZIP")

        RouteProbe(true, (System.nanoTime() - started) / 1_000_000)
    } catch (e: Exception) {
        RouteProbe(false, error = e.message ?: "连接失败")
    } finally {
        conn?.disconnect()
    }
}

suspend fun probeAllGithubRoutes(routes: List<GithubRoute>): Map<String, RouteProbe> = coroutineScope {
    routes.map { route -> async(Dispatchers.IO) { route.id to probeGithubRoute(route) } }.awaitAll().toMap()
}

// --- 新增：自定义模式数据模型与存储助手 ---
data class CustomTask(
    val id: String,
    var name: String,
    var url: String,
    var boundPath: String,
    var isSelected: Boolean = false, // 是否被勾选
    var isExpanded: Boolean = true   // 是否展开面板
)

fun loadCustomTasks(jsonStr: String): List<CustomTask> {
    val list = mutableListOf<CustomTask>()
    try {
        val array = org.json.JSONArray(jsonStr)
        for (i in 0 until array.length()) {
            val obj = array.getJSONObject(i)
            list.add(CustomTask(
                id = obj.optString("id", java.util.UUID.randomUUID().toString()),
                name = obj.optString("name", ""),
                url = obj.optString("url", ""),
                boundPath = obj.optString("boundPath", "DEFAULT"),
                isSelected = obj.optBoolean("isSelected", false),
                isExpanded = obj.optBoolean("isExpanded", true)
            ))
        }
    } catch (e: Exception) { e.printStackTrace() }
    return list
}

fun saveCustomTasks(tasks: List<CustomTask>, sharedPref: android.content.SharedPreferences) {
    val array = org.json.JSONArray()
    tasks.forEach {
        val obj = org.json.JSONObject()
        obj.put("id", it.id)
        obj.put("name", it.name)
        obj.put("url", it.url)
        obj.put("boundPath", it.boundPath)
        obj.put("isSelected", it.isSelected)
        obj.put("isExpanded", it.isExpanded)
        array.put(obj)
    }
    sharedPref.edit().putString("custom_tasks_data", array.toString()).apply()
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(
                colorScheme = lightColorScheme(
                    primary = MorandiGreen, onPrimary = Color.White,
                    secondaryContainer = MorandiLightGreen, outline = MorandiBorder
                )
            ) {
                Surface(modifier = Modifier.fillMaxSize(), color = Color(0xFFFAFAFA)) {
                    WanxiangDownloaderApp()
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun WanxiangDownloaderApp() {
    val context = LocalContext.current
    val sharedPref = context.getSharedPreferences("WanxiangPrefs", Context.MODE_PRIVATE)

    // 获取当前本地版本
    val localVersionName = remember {
        try {
            context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "1.0"
        } catch (e: Exception) {
            "1.0"
        }
    }

    var showPermissionDialog by remember { mutableStateOf(false) }

    if (showPermissionDialog) {
        AlertDialog(
            onDismissRequest = { },
            title = { Text("需要存储访问权限", fontWeight = FontWeight.Bold, fontSize = 18.sp, color = MorandiDarkGreen) },
            text = {
                Text(
                    text = "该权限仅用于写入手机根目录的 /rime。\n\n" +
                           "通过系统文件框架添加的小企鹅目录使用独立的 SAF 授权，不受此权限影响。即使暂不授权，已添加的 SAF 目录仍会继续分发。",
                    fontSize = 14.sp, lineHeight = 20.sp, color = Color.DarkGray
                )
            },
            confirmButton = {
                Button(
                    onClick = {
                        showPermissionDialog = false
                        val intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
                        intent.data = Uri.parse("package:${context.packageName}")
                        context.startActivity(intent)
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = MorandiGreen)
                ) { 
                    Text("去授权", fontWeight = FontWeight.Bold) 
                }
            },
            dismissButton = {
                TextButton(onClick = { showPermissionDialog = false }) { 
                    Text("暂不更新", color = Color.Gray) 
                }
            },
            containerColor = Color.White
        )
    }

    var isPro by remember { mutableStateOf(sharedPref.getBoolean("is_pro", true)) }
    var auxScheme by remember { mutableStateOf(sharedPref.getString("aux_scheme", "zrm") ?: "zrm") }
    var updateChannel by remember { mutableStateOf(sharedPref.getString("update_channel", "Stable") ?: "Stable") }

    var githubToken by remember { mutableStateOf(sharedPref.getString("gh_token", "") ?: "") }
    var githubRoutes by remember { mutableStateOf(loadGithubRoutes(sharedPref)) }
    var selectedRouteId by remember {
        val savedId = sharedPref.getString("selected_github_route", OFFICIAL_ROUTE_ID) ?: OFFICIAL_ROUTE_ID
        mutableStateOf(if (githubRoutes.any { it.id == savedId }) savedId else OFFICIAL_ROUTE_ID)
    }
    var routeProbes by remember { mutableStateOf<Map<String, RouteProbe>>(emptyMap()) }
    var isTestingRoutes by remember { mutableStateOf(false) }
    var showAddProxyDialog by remember { mutableStateOf(false) }
    var newProxyName by remember { mutableStateOf("") }
    var newProxyPrefix by remember { mutableStateOf("") }
    var pendingDeleteRouteId by remember { mutableStateOf<String?>(null) }
    var lowSpeedFallbackEnabled by remember {
        mutableStateOf(sharedPref.getBoolean("low_speed_fallback_enabled", true))
    }
    var minProxySpeedKbps by remember {
        mutableStateOf(sharedPref.getInt("min_proxy_speed_kbps", DEFAULT_MIN_PROXY_SPEED_KBPS))
    }

    var excludeRulesText by remember {
        mutableStateOf(sharedPref.getString("exclude_rules", DEFAULT_EXCLUDE_RULES) ?: DEFAULT_EXCLUDE_RULES)
    }
    var showAdvancedRules by remember { mutableStateOf(false) }
    val coroutineScope = rememberCoroutineScope()

    // 路径记忆（有序保存）：SAF 与 /rime 可以同时存在，部署时始终先 SAF、后 /rime。
    var savedPaths by remember { mutableStateOf(loadDeployPaths(sharedPref)) }

    val dirPickerLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            context.contentResolver.takePersistableUriPermission(
                uri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            )
            val newPaths = (savedPaths + uri.toString()).distinct()
            savedPaths = newPaths
            saveDeployPaths(newPaths, sharedPref)
        }
    }

    // 版本云端探测
    var latestStableTag by remember { mutableStateOf("v1.0.0") }
    var cloudVersionName by remember { mutableStateOf("") }
    var updaterDownloadUrl by remember { mutableStateOf("") }
    var updateCheckSource by remember { mutableStateOf("") }
    var isCheckingUpdate by remember { mutableStateOf(true) }
    var updateCheckNonce by remember { mutableStateOf(0) }

    // 启动时测速一次；删除或添加路线后不自动测速。
    LaunchedEffect(Unit) {
        isTestingRoutes = true
        val results = probeAllGithubRoutes(githubRoutes)
        routeProbes = results

        results.filterValues { it.ok }.minByOrNull { it.value.latencyMs }?.key?.let { bestRouteId ->
            selectedRouteId = bestRouteId
            sharedPref.edit().putString("selected_github_route", bestRouteId).apply()
        }
        isTestingRoutes = false
    }

    // 主方案版本检测：GitHub API失败时可用CNB补充正式版Tag。
    // 更新器自身检测：仅检查GitHub，CNB没有Android安装包，不显示或尝试CNB兜底。
    LaunchedEffect(selectedRouteId, githubRoutes, updateCheckNonce) {
        isCheckingUpdate = true
        updateCheckSource = ""
        cloudVersionName = ""
        updaterDownloadUrl = ""

        var detectedStableTag: String? = null
        var detectedUpdaterName: String? = null
        var detectedUpdaterUrl: String? = null
        var updaterSourceText = ""

        val mainJson = fetchGithubApiJson(
            "https://api.github.com/repos/amzxyz/rime-wanxiang/releases/latest",
            githubRoutes,
            selectedRouteId,
            githubToken
        )

        if (!mainJson.isNullOrBlank()) {
            try {
                detectedStableTag = org.json.JSONObject(mainJson).optString("tag_name").ifBlank { null }
            } catch (_: Exception) {
            }
        }

        var cnbMainReleases: org.json.JSONArray? = null
        if (detectedStableTag == null) {
            cnbMainReleases = fetchCnbReleases("rime-wanxiang")
            detectedStableTag = findLatestStableCnbTag(cnbMainReleases)
        }

        val toolJson = fetchGithubApiJson(
            "https://api.github.com/repos/amzxyz/RIME-LMDG/releases/tags/tool",
            githubRoutes,
            selectedRouteId,
            githubToken
        )

        if (!toolJson.isNullOrBlank()) {
            try {
                val assets = org.json.JSONObject(toolJson).optJSONArray("assets")
                if (assets != null) {
                    for (i in 0 until assets.length()) {
                        val asset = assets.optJSONObject(i) ?: continue
                        val name = asset.optString("name")
                        if (name.startsWith("Wanxiang-Updater-Android") && name.endsWith(".apk", true)) {
                            detectedUpdaterName = name
                            detectedUpdaterUrl = asset.optString("browser_download_url")
                            updaterSourceText = "GitHub API"
                            break
                        }
                    }
                }
            } catch (_: Exception) {
            }
        }

        detectedStableTag?.let { latestStableTag = it }
        detectedUpdaterName?.let { name ->
            cloudVersionName = Regex("""Wanxiang-Updater-Android.*?(\d+\.\d+(?:\.\d+)?)""")
                .find(name)?.groupValues?.get(1).orEmpty()
        }
        updaterDownloadUrl = detectedUpdaterUrl.orEmpty()
        updateCheckSource = updaterSourceText.ifBlank { "仅GitHub检查失败" }
        isCheckingUpdate = false
    }

    if (showAddProxyDialog) {
        AlertDialog(
            onDismissRequest = { showAddProxyDialog = false },
            title = { Text("添加GitHub代理") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedTextField(
                        value = newProxyName,
                        onValueChange = { newProxyName = it },
                        label = { Text("显示名称") },
                        singleLine = true
                    )
                    OutlinedTextField(
                        value = newProxyPrefix,
                        onValueChange = { newProxyPrefix = it },
                        label = { Text("代理前缀") },
                        supportingText = { Text("例如：https://proxy.example/") },
                        singleLine = true
                    )
                }
            },
            confirmButton = {
                val normalizedPrefix = normalizeProxyPrefix(newProxyPrefix)
                val canAdd = newProxyName.trim().isNotBlank() &&
                    normalizedPrefix != null &&
                    githubRoutes.none { it.prefix == normalizedPrefix }

                TextButton(
                    onClick = {
                        val newRoute = GithubRoute(UUID.randomUUID().toString(), newProxyName.trim(), normalizedPrefix!!)
                        githubRoutes = githubRoutes + newRoute
                        selectedRouteId = newRoute.id
                        routeProbes = routeProbes - newRoute.id
                        saveGithubRoutes(githubRoutes, sharedPref)
                        sharedPref.edit().putString("selected_github_route", newRoute.id).apply()
                        newProxyName = ""
                        newProxyPrefix = ""
                        showAddProxyDialog = false
                    },
                    enabled = canAdd
                ) { Text("添加") }
            },
            dismissButton = {
                TextButton(onClick = { showAddProxyDialog = false }) { Text("取消") }
            }
        )
    }

    pendingDeleteRouteId?.let { routeId ->
        val route = githubRoutes.firstOrNull { it.id == routeId }
        if (route != null && route.id != OFFICIAL_ROUTE_ID) {
            AlertDialog(
                onDismissRequest = { pendingDeleteRouteId = null },
                title = { Text("删除代理路线") },
                text = { Text("确定删除 ${route.name}？\n${route.prefix}") },
                confirmButton = {
                    TextButton(
                        onClick = {
                            githubRoutes = githubRoutes.filterNot { it.id == route.id }
                            routeProbes = routeProbes - route.id

                            if (selectedRouteId == route.id) {
                                selectedRouteId = OFFICIAL_ROUTE_ID
                                sharedPref.edit().putString("selected_github_route", OFFICIAL_ROUTE_ID).apply()
                            }

                            saveGithubRoutes(githubRoutes, sharedPref)
                            pendingDeleteRouteId = null
                        }
                    ) { Text("删除", color = Color.Red) }
                },
                dismissButton = {
                    TextButton(onClick = { pendingDeleteRouteId = null }) { Text("取消") }
                }
            )
        }
    }

    // 左侧主更新专用状态分离
    var isMainDownloading by remember { mutableStateOf(false) }
    var mainActiveTasks by remember { mutableStateOf<List<TaskState>>(emptyList()) }

    // 右侧自定义专用状态分离
    var customActiveTasks by remember { mutableStateOf<List<TaskState>>(emptyList()) }
    val auxMap = mapOf("zrm" to "自然码", "wx" to "万象", "flypy" to "小鹤", "moqi" to "墨奇", "hanxin" to "汉心", "shouyou" to "首右", "shyplus" to "首右+", "tiger" to "虎码", "wubi" to "五笔")

    var selectedTabIndex by remember { mutableStateOf(0) }
    var customTasks by remember { mutableStateOf(loadCustomTasks(sharedPref.getString("custom_tasks_data", "[]") ?: "[]")) }

    Column(modifier = Modifier.fillMaxSize()) {
        TabRow(
            selectedTabIndex = selectedTabIndex,
            containerColor = MorandiLightGreen,
            contentColor = MorandiDarkGreen
        ) {
            Tab(
                selected = selectedTabIndex == 0,
                onClick = { selectedTabIndex = 0 },
                text = { Text("万象更新", fontWeight = FontWeight.Bold) }
            )
            Tab(
                selected = selectedTabIndex == 1,
                onClick = { selectedTabIndex = 1 },
                text = { Text("自定义模式", fontWeight = FontWeight.Bold) }
            )
        }

        if (selectedTabIndex == 0) {
            Column(modifier = Modifier.padding(16.dp).verticalScroll(rememberScrollState()).weight(1f)) {
                Text("📱 万象拼音更新器", fontSize = 24.sp, fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
                Text("v$localVersionName • 全功能终极版", fontSize = 12.sp, color = Color.Gray)
                Spacer(modifier = Modifier.height(16.dp))

                Card(
                    colors = CardDefaults.cardColors(containerColor = Color.White), 
                    border = CardDefaults.outlinedCardBorder(true), 
                    elevation = CardDefaults.cardElevation(2.dp),
                    modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp)
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically, 
                        modifier = Modifier.padding(12.dp).fillMaxWidth()
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            val hasNewVersion = !isCheckingUpdate && cloudVersionName.isNotEmpty() && isRemoteVersionNewer(cloudVersionName, localVersionName)
                            Text("🔧 更新器自身检测", fontWeight = FontWeight.Bold, color = Color.DarkGray, fontSize = 14.sp)
                            Text(
                                text = if (isCheckingUpdate) "正在通过GitHub检测..."
                                       else if (cloudVersionName.isEmpty()) "GitHub未发现有效更新包"
                                       else if (hasNewVersion) "发现新版本: v$cloudVersionName"
                                       else "已是最新版本",
                                fontSize = 12.sp,
                                color = if (hasNewVersion) MorandiGreen else Color.Gray
                            )
                            if (!isCheckingUpdate) {
                                Text("软件检测：$updateCheckSource", fontSize = 10.sp, color = Color.Gray)
                            }
                        }

                        val hasNewVersion = !isCheckingUpdate && cloudVersionName.isNotEmpty() && isRemoteVersionNewer(cloudVersionName, localVersionName)
                        Column(horizontalAlignment = Alignment.End) {
                            Button(
                                onClick = {
                                    if (updaterDownloadUrl.isNotBlank()) {
                                        val preferredUrl = buildGithubCandidates(updaterDownloadUrl, githubRoutes, selectedRouteId).firstOrNull()?.url ?: updaterDownloadUrl
                                        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(preferredUrl)))
                                    }
                                },
                                enabled = hasNewVersion,
                                colors = ButtonDefaults.buttonColors(containerColor = if (hasNewVersion) MorandiGreen else Color.LightGray),
                                modifier = Modifier.height(32.dp),
                                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 0.dp)
                            ) {
                                Text(if (hasNewVersion) "立即更新" else "无需操作", fontSize = 12.sp, fontWeight = FontWeight.Bold)
                            }
                            TextButton(
                                onClick = { updateCheckNonce++ },
                                enabled = !isCheckingUpdate,
                                contentPadding = PaddingValues(0.dp),
                                modifier = Modifier.height(28.dp)
                            ) {
                                Text("重新检测", fontSize = 11.sp)
                            }
                        }
                    }
                }

                Card(
                    colors = CardDefaults.cardColors(containerColor = MorandiLightGreen), 
                    border = CardDefaults.outlinedCardBorder(true), 
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text("📁 目标集 (同时分发至以下目录)", fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
                        Spacer(modifier = Modifier.height(8.dp))
                        
                        if (savedPaths.isEmpty()) {
                            Text("⚠️ 未配置任何目标路径，将无法解压文件！", fontSize = 12.sp, color = Color.Red, modifier = Modifier.padding(bottom = 8.dp))
                        }

                        savedPaths.forEach { pathStr ->
                            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                                Text(
                                    text = if (pathStr == "DEFAULT") "🎯 默认: 手机根目录 /rime" else "🎯 授权: ${Uri.decode(pathStr).substringAfterLast(":")}",
                                    fontSize = 13.sp, color = Color.DarkGray, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis
                                )
                                TextButton(
                                    onClick = {
                                        if (pathStr != "DEFAULT") {
                                            runCatching {
                                                context.contentResolver.releasePersistableUriPermission(
                                                    Uri.parse(pathStr),
                                                    Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                                                )
                                            }
                                        }

                                        val newPaths = savedPaths - pathStr
                                        savedPaths = newPaths
                                        saveDeployPaths(newPaths, sharedPref)
                                    },
                                    contentPadding = PaddingValues(0.dp), 
                                    modifier = Modifier.height(24.dp)
                                ) { 
                                    Text("移除", fontSize = 12.sp, color = Color.Red) 
                                }
                            }
                        }
                        
                        Divider(color = MorandiBorder, modifier = Modifier.padding(vertical = 8.dp))
                        
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(
                                onClick = { dirPickerLauncher.launch(null) }, 
                                modifier = Modifier.weight(1f).height(36.dp)
                            ) { 
                                Text("➕ 添加授权目录", fontSize = 12.sp) 
                            }
                            if (!savedPaths.contains("DEFAULT")) {
                                TextButton(
                                    onClick = {
                                        val newPaths = (savedPaths + "DEFAULT").distinct()
                                        savedPaths = newPaths
                                        saveDeployPaths(newPaths, sharedPref)

                                        if (!canWriteDefaultRime()) {
                                            showPermissionDialog = true
                                        }
                                    },
                                    modifier = Modifier.height(36.dp)
                                ) { 
                                    Text("➕ 恢复默认", fontSize = 12.sp, color = MorandiDarkGreen) 
                                }
                            }
                        }
                    }
                }
                Spacer(modifier = Modifier.height(12.dp))

                Card(colors = CardDefaults.cardColors(containerColor = Color.White), border = CardDefaults.outlinedCardBorder(true), modifier = Modifier.fillMaxWidth()) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text("🚀 更新通道", fontWeight = FontWeight.Bold, color = Color.DarkGray)
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(selected = updateChannel == "Stable", onClick = { updateChannel = "Stable"; sharedPref.edit().putString("update_channel", "Stable").apply() })
                            Text("正式版 (${latestStableTag})", fontSize = 14.sp)
                            Spacer(modifier = Modifier.width(16.dp))
                            RadioButton(selected = updateChannel == "Preview", onClick = { updateChannel = "Preview"; sharedPref.edit().putString("update_channel", "Preview").apply() })
                            Text("预览版", fontSize = 14.sp, color = MorandiGreen)
                        }
                        Divider(color = MorandiLightGreen, modifier = Modifier.padding(vertical = 8.dp))
                        Text("📦 方案版本", fontWeight = FontWeight.Bold, color = Color.DarkGray)
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(selected = isPro, onClick = { isPro = true; sharedPref.edit().putBoolean("is_pro", true).apply() })
                            Text("Pro版", fontSize = 14.sp)
                            Spacer(modifier = Modifier.width(16.dp))
                            RadioButton(selected = !isPro, onClick = { isPro = false; sharedPref.edit().putBoolean("is_pro", false).apply() })
                            Text("Base版", fontSize = 14.sp)
                        }
                        
                        if (isPro) {
                            Divider(color = MorandiLightGreen, modifier = Modifier.padding(vertical = 8.dp))
                            Text("⌨️ 辅助类型：", fontWeight = FontWeight.Bold, color = Color.DarkGray, fontSize = 13.sp, modifier = Modifier.padding(bottom = 4.dp))
                            
                            FlowRow(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                auxMap.forEach { (key, name) ->
                                    FilterChip(
                                        selected = (auxScheme == key), 
                                        onClick = { 
                                            auxScheme = key 
                                            sharedPref.edit().putString("aux_scheme", key).apply() 
                                        }, 
                                        label = { Text(name, fontSize = 12.sp) }
                                    )
                                }
                            }
                        }
                    }
                }
                Spacer(modifier = Modifier.height(12.dp))

                Card(colors = CardDefaults.cardColors(containerColor = Color.White), border = CardDefaults.outlinedCardBorder(true), modifier = Modifier.fillMaxWidth()) {
                    Column(modifier = Modifier.fillMaxWidth()) {
                        TextButton(
                            onClick = { showAdvancedRules = !showAdvancedRules }, 
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp)
                        ) {
                            Text(if (showAdvancedRules) "▼ 收起护盾配置" else "▶ 展开防覆盖保护配置 (高级)", color = MorandiDarkGreen, fontWeight = FontWeight.Bold)
                        }
                        AnimatedVisibility(visible = showAdvancedRules) {
                            Column(modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 16.dp)) {
                                Text("相对路径命中正则且本地已有该文件，强制跳过覆盖：", fontSize = 11.sp, color = Color.Gray, modifier = Modifier.padding(bottom = 8.dp))
                                OutlinedTextField(
                                    value = excludeRulesText,
                                    onValueChange = { 
                                        excludeRulesText = it
                                        sharedPref.edit().putString("exclude_rules", it).apply() 
                                    },
                                    modifier = Modifier.fillMaxWidth().height(160.dp),
                                    textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp, fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace)
                                )
                                
                                TextButton(
                                    onClick = { 
                                        excludeRulesText = DEFAULT_EXCLUDE_RULES
                                        sharedPref.edit().putString("exclude_rules", DEFAULT_EXCLUDE_RULES).apply()
                                    }, 
                                    modifier = Modifier.align(Alignment.End)
                                ) { 
                                    Text("恢复默认规则", fontSize = 12.sp, color = Color.Red) 
                                }
                            }
                        }
                    }
                }
                Spacer(modifier = Modifier.height(12.dp))

                Card(colors = CardDefaults.cardColors(containerColor = Color.White), border = CardDefaults.outlinedCardBorder(true), modifier = Modifier.fillMaxWidth()) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text("🌐 GitHub下载路线", fontWeight = FontWeight.Bold, color = Color.DarkGray)
                        Text("按当前路线优先下载，其他代理依次补位，全部失败后自动回退CNB。", fontSize = 11.sp, color = Color.Gray)

                        Row(
                            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Switch(
                                checked = lowSpeedFallbackEnabled,
                                onCheckedChange = { enabled ->
                                    lowSpeedFallbackEnabled = enabled
                                    sharedPref.edit().putBoolean("low_speed_fallback_enabled", enabled).apply()
                                }
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text("代理低速自动切换CNB", fontSize = 13.sp, fontWeight = FontWeight.Bold, color = Color.DarkGray)
                            }
                        }

                        AnimatedVisibility(visible = lowSpeedFallbackEnabled) {
                            Column(modifier = Modifier.fillMaxWidth().padding(top = 4.dp, bottom = 4.dp)) {
                                Text("最低速度（观察5秒后判断）", fontSize = 11.sp, color = Color.Gray)
                                FlowRow(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                                    verticalArrangement = Arrangement.spacedBy(4.dp)
                                ) {
                                    listOf(64, 128, 256, 512).forEach { speed ->
                                        FilterChip(
                                            selected = minProxySpeedKbps == speed,
                                            onClick = {
                                                minProxySpeedKbps = speed
                                                sharedPref.edit().putInt("min_proxy_speed_kbps", speed).apply()
                                            },
                                            label = { Text("${speed}KB/s", fontSize = 11.sp) }
                                        )
                                    }
                                }
                            }
                        }

                        Spacer(modifier = Modifier.height(8.dp))

                        val availableRouteIds = routeProbes.filterValues { it.ok }
                            .toList()
                            .sortedBy { it.second.latencyMs }
                            .map { it.first }

                        FlowRow(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp)
                        ) {
                            githubRoutes.forEach { route ->
                                val probe = routeProbes[route.id]
                                val rank = availableRouteIds.indexOf(route.id)
                                val statusColor = when {
                                    probe == null -> Color.Gray
                                    !probe.ok -> Color(0xFFC46A6A)
                                    rank == 0 -> MorandiGreen
                                    rank == 1 -> Color(0xFFC9A44C)
                                    else -> Color(0xFF8A6F6A)
                                }
                                val label = when {
                                    isTestingRoutes && probe == null -> "${route.name} 测速中"
                                    probe?.ok == true -> "${route.name} ${probe.latencyMs}ms"
                                    probe != null -> "${route.name} 不可用"
                                    else -> route.name
                                }

                                InputChip(
                                    selected = selectedRouteId == route.id,
                                    onClick = {
                                        selectedRouteId = route.id
                                        sharedPref.edit().putString("selected_github_route", route.id).apply()
                                    },
                                    label = { Text(label, fontSize = 11.sp, color = statusColor) },
                                    trailingIcon = if (route.id != OFFICIAL_ROUTE_ID) {
                                        {
                                            Text(
                                                "×",
                                                fontSize = 16.sp,
                                                color = Color.Red,
                                                modifier = Modifier.clickable { pendingDeleteRouteId = route.id }
                                            )
                                        }
                                    } else null
                                )
                            }
                        }

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            OutlinedButton(
                                onClick = {
                                    coroutineScope.launch {
                                        isTestingRoutes = true
                                        routeProbes = probeAllGithubRoutes(githubRoutes)
                                        routeProbes.filterValues { it.ok }.minByOrNull { it.value.latencyMs }?.key?.let { bestId ->
                                            selectedRouteId = bestId
                                            sharedPref.edit().putString("selected_github_route", bestId).apply()
                                        }
                                        isTestingRoutes = false
                                    }
                                },
                                enabled = !isTestingRoutes,
                                modifier = Modifier.weight(1f).height(38.dp),
                                contentPadding = PaddingValues(horizontal = 8.dp)
                            ) {
                                Text(if (isTestingRoutes) "测速中..." else "测速最优路线", fontSize = 11.sp)
                            }

                            OutlinedButton(
                                onClick = { showAddProxyDialog = true },
                                enabled = !isTestingRoutes,
                                modifier = Modifier.weight(1f).height(38.dp),
                                contentPadding = PaddingValues(horizontal = 8.dp)
                            ) {
                                Text("添加代理", fontSize = 11.sp)
                            }
                        }

                        TextButton(
                            onClick = {
                                githubRoutes = DEFAULT_GITHUB_ROUTES
                                routeProbes = emptyMap()
                                selectedRouteId = OFFICIAL_ROUTE_ID
                                saveGithubRoutes(githubRoutes, sharedPref)
                                sharedPref.edit().putString("selected_github_route", OFFICIAL_ROUTE_ID).apply()
                            },
                            modifier = Modifier.align(Alignment.End),
                            contentPadding = PaddingValues(0.dp)
                        ) {
                            Text("恢复默认代理", fontSize = 11.sp, color = Color.Gray)
                        }

                        OutlinedTextField(
                            value = githubToken,
                            onValueChange = {
                                githubToken = it
                                sharedPref.edit().putString("gh_token", it).apply()
                            },
                            label = { Text("GitHub Token（仅官方请求使用）", fontSize = 12.sp) },
                            supportingText = { Text("Token不会发送给第三方代理或CNB。修改后点上方“重新检测”。", fontSize = 10.sp) },
                            visualTransformation = PasswordVisualTransformation(),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true
                        )
                    }
                }
                Spacer(modifier = Modifier.height(16.dp))

                val schemeStr = if (isPro) auxScheme else "base"
                val githubSchemaTag = if (updateChannel == "Stable") latestStableTag else "dict-nightly"
                val cnbSchemaTag = if (updateChannel == "Stable") latestStableTag else "v1.0.0"
                val schemaFileName = "rime-wanxiang-$schemeStr${if (isPro) "-fuzhu" else ""}.zip"
                val dictFileName = "${if (isPro) "pro-$schemeStr-fuzhu" else "base"}-dicts.zip"

                val schemaUrl = "https://github.com/amzxyz/rime-wanxiang/releases/download/$githubSchemaTag/$schemaFileName"
                val dictUrl = "https://github.com/amzxyz/rime-wanxiang/releases/download/dict-nightly/$dictFileName"
                val modelUrl = "https://github.com/amzxyz/RIME-LMDG/releases/download/LTS/wanxiang-lts-zh-hans.gram"

                val cnbFallbackUrls = mapOf(
                    schemaUrl to "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/$cnbSchemaTag/$schemaFileName",
                    dictUrl to "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/v1.0.0/$dictFileName",
                    modelUrl to "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/model/wanxiang-lts-zh-hans.gram"
                )

                val tasksMap = listOf(
                    "🚀 全量更新" to listOf(schemaUrl, dictUrl, modelUrl),
                    "⚙️ 仅方案" to listOf(schemaUrl),
                    "📖 仅词库" to listOf(dictUrl),
                    "🧠 仅模型" to listOf(modelUrl)
                )

                AnimatedVisibility(visible = mainActiveTasks.isNotEmpty()) {
                    Card(colors = CardDefaults.cardColors(containerColor = MorandiLightGreen), modifier = Modifier.fillMaxWidth().padding(bottom = 16.dp)) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Text("📥 任务进度", fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
                            mainActiveTasks.forEach { task ->
                                Column(modifier = Modifier.padding(vertical = 4.dp)) {
                                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                        Text(task.title, fontSize = 12.sp, modifier = Modifier.weight(1f), maxLines = 1)
                                        Text(task.status, fontSize = 11.sp, color = if (task.isError) Color.Red else Color.Gray)
                                    }
                                    if (task.progress < 0f) {
                                        LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                                    } else {
                                        LinearProgressIndicator(progress = task.progress, modifier = Modifier.fillMaxWidth())
                                    }
                                }
                            }
                        }
                    }
                }

                Text("执行操作:", fontWeight = FontWeight.Bold, color = Color.DarkGray)
                tasksMap.chunked(2).forEach { rowTasks ->
                    Row(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        rowTasks.forEach { (name, urls) ->
                            Button(
                                onClick = { 
                                    if (savedPaths.isEmpty()) return@Button 
                                    
                                    if (savedPaths.contains("DEFAULT") && !canWriteDefaultRime()) {
                                        // 只提醒 /rime 权限；任务仍继续，已授权的 SAF 目标不会被阻断。
                                        showPermissionDialog = true
                                    }

                                    val currentRules = excludeRulesText.lines().filter { it.isNotBlank() }
                                    executeTasks(
                                        urls = urls, 
                                        scope = coroutineScope, 
                                        setDownloading = { isMainDownloading = it }, 
                                        setTasks = { mainActiveTasks = it }, 
                                        token = githubToken, 
                                        targetPaths = savedPaths, 
                                        context = context,
                                        rules = currentRules,
                                        githubRoutes = githubRoutes,
                                        selectedRouteId = selectedRouteId,
                                        cnbFallbackUrls = cnbFallbackUrls,
                                        lowSpeedFallbackEnabled = lowSpeedFallbackEnabled,
                                        minProxySpeedKbps = minProxySpeedKbps
                                    )
                                },
                                modifier = Modifier.weight(1f).height(48.dp),
                                enabled = !isMainDownloading && savedPaths.isNotEmpty(),
                                shape = RoundedCornerShape(8.dp)
                            ) { 
                                Text(name, fontSize = 13.sp, fontWeight = FontWeight.Bold) 
                            }
                        }
                    }
                }
            }
        } else {
            CustomModeTab(
                customTasks = customTasks,
                savedPaths = savedPaths,
                onTasksChange = { newTasks ->
                    customTasks = newTasks
                    saveCustomTasks(newTasks, sharedPref)
                },
                coroutineScope = coroutineScope,
                setDownloading = {},
                setTasks = { customActiveTasks = it },
                context = context,
                activeTasks = customActiveTasks,
                githubRoutes = githubRoutes,
                selectedRouteId = selectedRouteId,
                githubToken = githubToken
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CustomModeTab(
    customTasks: List<CustomTask>,
    savedPaths: List<String>,
    onTasksChange: (List<CustomTask>) -> Unit,
    coroutineScope: kotlinx.coroutines.CoroutineScope,
    setDownloading: (Boolean) -> Unit,
    setTasks: (List<TaskState>) -> Unit,
    context: Context,
    activeTasks: List<TaskState>,
    githubRoutes: List<GithubRoute>,
    selectedRouteId: String,
    githubToken: String
) {
    var taskAwaitingPath by remember { mutableStateOf<String?>(null) }
    val isDownloading = activeTasks.isNotEmpty() && activeTasks.any { !it.isFinished && !it.isError }

    val customDirLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            context.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
            val pathStr = uri.toString()
            taskAwaitingPath?.let { taskId ->
                val updated = customTasks.map { task ->
                    if (task.id == taskId) task.copy(boundPath = pathStr) else task
                }
                onTasksChange(updated)
            }
            taskAwaitingPath = null
        }
    }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState())) {
        Text("🛠️ 自定义扩展模式", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
        Text("打勾并点击批量执行，或单独展开配置。本地文件与网络直链均支持。", fontSize = 12.sp, color = Color.Gray)
        Spacer(modifier = Modifier.height(16.dp))

        val selectedCount = customTasks.count { it.isSelected }
        AnimatedVisibility(visible = activeTasks.isNotEmpty() || selectedCount > 0) {
            Card(colors = CardDefaults.cardColors(containerColor = MorandiLightGreen), modifier = Modifier.fillMaxWidth().padding(bottom = 16.dp)) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                        Text(if (activeTasks.isNotEmpty()) "📥 实时进度" else "📦 待执行队列", fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
                        
                        if (selectedCount > 0 && !isDownloading) {
                            Button(
                                onClick = {
                                    val targets = customTasks.filter { it.isSelected && it.url.isNotBlank() && it.boundPath.isNotBlank() }
                                    if (targets.isEmpty()) return@Button
                                    
                                    coroutineScope.launch {
                                        setDownloading(true)
                                        val uiTasks = targets.map { t -> 
                                            val fName = t.url.substringAfterLast("/")
                                            TaskState("${t.name.ifBlank { "未命名" }} ($fName)", t.url)
                                        }
                                        setTasks(uiTasks)
                                        for ((taskData, uiState) in targets.zip(uiTasks)) {
                                            downloadAndDeployTask(uiState, githubToken, listOf(taskData.boundPath), context, emptyList(), githubRoutes, selectedRouteId)
                                            if (uiState.isError) break
                                        }
                                        setDownloading(false)
                                    }
                                },
                                modifier = Modifier.height(32.dp),
                                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 0.dp),
                                colors = ButtonDefaults.buttonColors(containerColor = MorandiGreen)
                            ) {
                                Text("批量下载/解压 ($selectedCount)", fontSize = 12.sp, fontWeight = FontWeight.Bold)
                            }
                        }
                    }

                    activeTasks.forEach { task ->
                        Column(modifier = Modifier.padding(top = 8.dp, bottom = 4.dp)) {
                            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                Text(task.title, fontSize = 12.sp, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                                Text(task.status, fontSize = 11.sp, color = if (task.isError) Color.Red else Color.DarkGray)
                            }
                            if (task.progress < 0f) {
                                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                            } else {
                                LinearProgressIndicator(progress = task.progress, modifier = Modifier.fillMaxWidth())
                            }
                        }
                    }
                }
            }
        }

        if (customTasks.isEmpty()) {
            Text("暂无自定义任务，请点击下方添加", fontSize = 14.sp, color = Color.Gray, modifier = Modifier.padding(vertical = 20.dp).align(Alignment.CenterHorizontally))
        }

        customTasks.forEachIndexed { index, task ->
            Card(
                colors = CardDefaults.cardColors(containerColor = if (task.isSelected) Color(0xFFF5F9F6) else Color.White),
                border = BorderStroke(1.dp, if (task.isSelected) MorandiGreen else MorandiBorder),
                modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp)
            ) {
                Column {
                    Row(
                        verticalAlignment = Alignment.CenterVertically, 
                        modifier = Modifier.fillMaxWidth().clickable { 
                            val updated = customTasks.toMutableList()
                            updated[index] = task.copy(isExpanded = !task.isExpanded)
                            onTasksChange(updated)
                        }.padding(start = 12.dp, end = 12.dp, top = 12.dp, bottom = 12.dp)
                    ) {
                        Box(
                            modifier = Modifier
                                .padding(end = 12.dp)
                                .size(22.dp)
                                .clip(CircleShape)
                                .clickable { 
                                    val updated = customTasks.toMutableList()
                                    updated[index] = task.copy(isSelected = !task.isSelected)
                                    onTasksChange(updated)
                                }
                                .background(if (task.isSelected) MorandiGreen else Color.Transparent, CircleShape)
                                .border(1.5.dp, if (task.isSelected) MorandiGreen else MorandiBorder, CircleShape),
                            contentAlignment = Alignment.Center
                        ) {
                            if (task.isSelected) {
                                Icon(
                                    imageVector = Icons.Default.Check,
                                    contentDescription = "已勾选",
                                    tint = Color.White,
                                    modifier = Modifier.size(16.dp)
                                )
                            }
                        }
                        
                        Text(
                            text = task.name.ifBlank { "未命名扩展任务" },
                            fontSize = 14.sp,
                            fontWeight = FontWeight.Bold,
                            color = if (task.isSelected) MorandiDarkGreen else Color.DarkGray,
                            modifier = Modifier.weight(1f)
                        )
                        Text(
                            text = if (task.isExpanded) "▲" else "▼",
                            color = MorandiBorder,
                            fontSize = 12.sp
                        )
                    }

                    AnimatedVisibility(visible = task.isExpanded) {
                        Column(modifier = Modifier.padding(start = 12.dp, end = 12.dp, bottom = 12.dp)) {
                            Divider(color = MorandiLightGreen, modifier = Modifier.padding(bottom = 12.dp))
                            
                            Text("任务别名 (选填)", fontSize = 11.sp, color = Color.Gray, modifier = Modifier.padding(bottom = 4.dp))
                            androidx.compose.foundation.text.BasicTextField(
                                value = task.name,
                                onValueChange = { newName -> val updated = customTasks.toMutableList(); updated[index] = task.copy(name = newName); onTasksChange(updated) },
                                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 13.sp, color = Color.DarkGray),
                                singleLine = true,
                                decorationBox = { innerTextField ->
                                    Box(contentAlignment = Alignment.CenterStart, modifier = Modifier.fillMaxWidth().height(38.dp).border(1.dp, MorandiBorder, RoundedCornerShape(6.dp)).padding(horizontal = 10.dp)) {
                                        if (task.name.isEmpty()) Text("如: 极速版扩展包", color = Color.LightGray, fontSize = 13.sp)
                                        innerTextField()
                                    }
                                }
                            )
                            Spacer(modifier = Modifier.height(10.dp))
                            
                            Text("直链 URL 或 绝对路径 (.zip)", fontSize = 11.sp, color = Color.Gray, modifier = Modifier.padding(bottom = 4.dp))
                            androidx.compose.foundation.text.BasicTextField(
                                value = task.url,
                                onValueChange = { newUrl -> val updated = customTasks.toMutableList(); updated[index] = task.copy(url = newUrl); onTasksChange(updated) },
                                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 13.sp, color = Color.DarkGray),
                                singleLine = true,
                                decorationBox = { innerTextField ->
                                    Box(contentAlignment = Alignment.CenterStart, modifier = Modifier.fillMaxWidth().height(38.dp).border(1.dp, MorandiBorder, RoundedCornerShape(6.dp)).padding(horizontal = 10.dp)) {
                                        if (task.url.isEmpty()) Text("https://... 或 /storage/...", color = Color.LightGray, fontSize = 13.sp)
                                        innerTextField()
                                    }
                                }
                            )
                            Spacer(modifier = Modifier.height(10.dp))

                            Text("目标解压路径", fontSize = 11.sp, color = Color.Gray, modifier = Modifier.padding(bottom = 4.dp))
                            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                                androidx.compose.foundation.text.BasicTextField(
                                    value = if (task.boundPath == "DEFAULT") "默认: /rime" else "授权: ${Uri.decode(task.boundPath).substringAfterLast(":")}",
                                    onValueChange = {},
                                    readOnly = true,
                                    textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp, color = Color.DarkGray),
                                    singleLine = true,
                                    modifier = Modifier.weight(1f),
                                    decorationBox = { innerTextField ->
                                        Box(contentAlignment = Alignment.CenterStart, modifier = Modifier.fillMaxWidth().height(38.dp).background(Color(0xFFF9F9F9), RoundedCornerShape(6.dp)).border(1.dp, MorandiBorder, RoundedCornerShape(6.dp)).padding(horizontal = 10.dp)) {
                                            innerTextField()
                                        }
                                    }
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                    Button(
                                        onClick = { taskAwaitingPath = task.id; customDirLauncher.launch(null) },
                                        modifier = Modifier.height(38.dp), 
                                        shape = RoundedCornerShape(6.dp), 
                                        contentPadding = PaddingValues(horizontal = 12.dp), 
                                        colors = ButtonDefaults.buttonColors(containerColor = MorandiDarkGreen)
                                    ) { Text("配置目录", fontSize = 12.sp) }
                                    if (task.boundPath != "DEFAULT") {
                                        TextButton(onClick = { val updated = customTasks.toMutableList(); updated[index] = task.copy(boundPath = "DEFAULT"); onTasksChange(updated) }, modifier = Modifier.height(20.dp), contentPadding = PaddingValues(0.dp)) {
                                            Text("重置", fontSize = 10.sp, color = Color.Gray)
                                        }
                                    }
                                }
                            }
                            
                            Spacer(modifier = Modifier.height(16.dp))
                            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                                TextButton(onClick = { val updated = customTasks.toMutableList(); updated.removeAt(index); onTasksChange(updated) }) {
                                    Text("删除任务", color = Color.Red, fontSize = 12.sp)
                                }
                                Button(
                                    onClick = {
                                        if (task.url.isNotBlank() && task.boundPath.isNotBlank()) {
                                            executeTasks(
                                                urls = listOf(task.url),
                                                scope = coroutineScope,
                                                setDownloading = setDownloading,
                                                setTasks = setTasks,
                                                token = githubToken,
                                                targetPaths = listOf(task.boundPath),
                                                context = context,
                                                rules = emptyList(),
                                                githubRoutes = githubRoutes,
                                                selectedRouteId = selectedRouteId
                                            )
                                        }
                                    },
                                    enabled = !isDownloading && task.url.isNotBlank() && task.boundPath.isNotBlank(), 
                                    shape = RoundedCornerShape(6.dp), 
                                    colors = ButtonDefaults.buttonColors(containerColor = MorandiGreen)
                                ) { Text("独立执行此任务", fontSize = 12.sp, fontWeight = FontWeight.Bold) }
                            }
                        }
                    }
                }
            }
        }

        OutlinedButton(
            onClick = {
                val newTask = CustomTask(java.util.UUID.randomUUID().toString(), "", "", "DEFAULT")
                onTasksChange(customTasks + newTask)
            },
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            shape = RoundedCornerShape(8.dp)
        ) {
            Text("➕ 添加自定义任务", color = MorandiDarkGreen)
        }
    }
}

fun executeTasks(
    urls: List<String>,
    scope: kotlinx.coroutines.CoroutineScope,
    setDownloading: (Boolean) -> Unit,
    setTasks: (List<TaskState>) -> Unit,
    token: String,
    targetPaths: List<String>,
    context: Context,
    rules: List<String>,
    githubRoutes: List<GithubRoute> = DEFAULT_GITHUB_ROUTES,
    selectedRouteId: String = OFFICIAL_ROUTE_ID,
    cnbFallbackUrls: Map<String, String> = emptyMap(),
    lowSpeedFallbackEnabled: Boolean = true,
    minProxySpeedKbps: Int = DEFAULT_MIN_PROXY_SPEED_KBPS
) {
    scope.launch {
        setDownloading(true)
        val activeTasks = urls.map { url ->
            val fileName = url.substringBefore("?").substringAfterLast("/")
            val title = when {
                fileName.contains("dicts", true) -> "词库包"
                fileName.contains("gram", true) -> "模型"
                else -> "方案"
            }
            TaskState("$title ($fileName)", url, cnbFallbackUrls[url])
        }

        setTasks(activeTasks)

        for (task in activeTasks) {
            downloadAndDeployTask(
                task = task,
                token = token,
                targetPaths = targetPaths,
                context = context,
                rules = rules,
                githubRoutes = githubRoutes,
                selectedRouteId = selectedRouteId,
                lowSpeedFallbackEnabled = lowSpeedFallbackEnabled,
                minProxySpeedKbps = minProxySpeedKbps
            )
            if (task.isError) break
        }

        setDownloading(false)
    }
}

fun isUsableZip(file: File): Boolean {
    return try {
        ZipFile(file).use { zip -> zip.entries().hasMoreElements() }
    } catch (_: Exception) {
        false
    }
}

fun looksLikeErrorPayload(file: File): Boolean {
    return try {
        val prefix = file.inputStream().buffered().use { input ->
            val buffer = ByteArray(512)
            val count = input.read(buffer)
            if (count <= 0) "" else String(buffer, 0, count, Charsets.UTF_8)
        }.trimStart().lowercase()

        prefix.startsWith("<!doctype html") ||
            prefix.startsWith("<html") ||
            prefix.startsWith("{\"message\"") ||
            prefix.startsWith("{\"error\"") ||
            prefix.startsWith("access denied") ||
            prefix.startsWith("bad gateway")
    } catch (_: Exception) {
        false
    }
}

fun sanitizedFileName(url: String): String {
    val raw = url.substringBefore("?").substringAfterLast("/").ifBlank { "download.bin" }
    return raw.replace(Regex("""[\\/:*?"<>|]"""), "_")
}

fun formatDownloadSpeed(bytesPerSecond: Long): String {
    return if (bytesPerSecond >= 1024L * 1024L) {
        String.format("%.1fMB/s", bytesPerSecond / 1024.0 / 1024.0)
    } else {
        "${bytesPerSecond / 1024L}KB/s"
    }
}

suspend fun downloadAndDeployTask(
    task: TaskState,
    token: String,
    targetPaths: List<String>,
    context: Context,
    rules: List<String>,
    githubRoutes: List<GithubRoute> = DEFAULT_GITHUB_ROUTES,
    selectedRouteId: String = OFFICIAL_ROUTE_ID,
    lowSpeedFallbackEnabled: Boolean = true,
    minProxySpeedKbps: Int = DEFAULT_MIN_PROXY_SPEED_KBPS
) {
    withContext(Dispatchers.IO) {
        val stagingDir = File(context.cacheDir, "wanxiang_staging/${UUID.randomUUID()}")
        val tmpFile = File(stagingDir, "${sanitizedFileName(task.url)}.tmp")
        var success = false
        var lastErrorMsg = ""
        var downloadedFrom = ""

        try {
            if (!stagingDir.mkdirs() && !stagingDir.isDirectory) {
                throw Exception("无法创建临时目录")
            }

            withContext(Dispatchers.Main) {
                task.isFinished = false
                task.isError = false
                task.progress = 0f
                task.status = "准备中..."
            }

            val isLocalFile = task.url.startsWith("/") || task.url.startsWith("file://") || task.url.startsWith("content://")

            if (isLocalFile) {
                try {
                    withContext(Dispatchers.Main) {
                        task.status = "读取本地文件..."
                        task.progress = -1f
                    }

                    val uri = if (task.url.startsWith("/")) Uri.fromFile(File(task.url)) else Uri.parse(task.url)
                    context.contentResolver.openInputStream(uri)?.use { input ->
                        FileOutputStream(tmpFile).buffered().use { output -> input.copyTo(output) }
                    } ?: throw Exception("找不到文件或无权限读取该本地路径")

                    if (!tmpFile.exists() || tmpFile.length() == 0L) throw Exception("本地文件为空")
                    success = true
                    downloadedFrom = "本地文件"

                    withContext(Dispatchers.Main) {
                        task.progress = 1f
                        task.status = "本地读取完成"
                    }
                } catch (e: Exception) {
                    lastErrorMsg = e.message ?: "本地文件读取异常"
                }
            } else {
                val candidates = buildGithubCandidates(task.url, githubRoutes, selectedRouteId, task.cnbFallbackUrl)
                val expectedZip = task.url.substringBefore("?").endsWith(".zip", true)

                var jumpDirectlyToCnb = false

                candidateLoop@ for (candidate in candidates) {
                    if (jumpDirectlyToCnb && !candidate.isCnb) continue

                    attemptLoop@ for (attempt in 1..2) {
                        var conn: HttpURLConnection? = null
                        val monitorLowSpeed = lowSpeedFallbackEnabled &&
                            candidate.usesProxy &&
                            !candidate.isCnb &&
                            !task.cnbFallbackUrl.isNullOrBlank()

                        try {
                            tmpFile.delete()

                            withContext(Dispatchers.Main) {
                                task.progress = 0f
                                task.status = when {
                                    candidate.isCnb -> "GitHub路线失败，切换CNB..."
                                    attempt > 1 -> "${candidate.name} 重试 $attempt/2"
                                    else -> "连接 ${candidate.name}..."
                                }
                            }

                            conn = URL(candidate.url).openConnection() as HttpURLConnection
                            conn.instanceFollowRedirects = true
                            conn.connectTimeout = 10000
                            conn.readTimeout = if (monitorLowSpeed) 10000 else 60000
                            conn.setRequestProperty("User-Agent", "WanxiangUpdater-Android")
                            conn.setRequestProperty("Accept-Encoding", "identity")

                            if (!candidate.usesProxy && candidate.url.startsWith("https://github.com/") && token.isNotBlank()) {
                                conn.setRequestProperty("Authorization", "Bearer $token")
                            }

                            val responseCode = conn.responseCode
                            if (responseCode !in 200..299) throw Exception("HTTP $responseCode")

                            val contentType = conn.contentType.orEmpty().lowercase()
                            if ("text/html" in contentType || "application/json" in contentType) {
                                throw Exception("服务器返回了错误页面")
                            }

                            val totalSize = conn.getHeaderFieldLong("Content-Length", -1L)
                            var downloaded = 0L
                            var lastUiUpdate = 0L
                            val transferStartedAt = System.currentTimeMillis()
                            var speedWindowStartedAt = transferStartedAt
                            var speedWindowStartBytes = 0L
                            val minSpeedBytesPerSecond = minProxySpeedKbps.coerceAtLeast(32) * 1024L

                            conn.inputStream.buffered().use { input ->
                                FileOutputStream(tmpFile).buffered().use { output ->
                                    val buffer = ByteArray(128 * 1024)
                                    while (true) {
                                        val count = input.read(buffer)
                                        if (count < 0) break

                                        output.write(buffer, 0, count)
                                        downloaded += count

                                        val now = System.currentTimeMillis()
                                        if (monitorLowSpeed &&
                                            now - transferStartedAt >= LOW_SPEED_GRACE_MS &&
                                            now - speedWindowStartedAt >= LOW_SPEED_WINDOW_MS
                                        ) {
                                            val windowMs = now - speedWindowStartedAt
                                            val windowBytes = downloaded - speedWindowStartBytes
                                            val speedBytesPerSecond = if (windowMs > 0L) windowBytes * 1000L / windowMs else Long.MAX_VALUE

                                            if (speedBytesPerSecond < minSpeedBytesPerSecond) {
                                                throw LowSpeedFallbackException(speedBytesPerSecond / 1024L)
                                            }

                                            speedWindowStartedAt = now
                                            speedWindowStartBytes = downloaded
                                        }

                                        if (now - lastUiUpdate >= 150L) {
                                            lastUiUpdate = now
                                            val elapsedMs = (now - transferStartedAt).coerceAtLeast(1L)
                                            val averageSpeed = downloaded * 1000L / elapsedMs
                                            val speedText = formatDownloadSpeed(averageSpeed)

                                            withContext(Dispatchers.Main) {
                                                if (totalSize > 0L) {
                                                    task.progress = (downloaded.toDouble() / totalSize.toDouble()).toFloat().coerceIn(0f, 1f)
                                                    task.status = "${candidate.name} ${String.format("%.1f", downloaded / 1024.0 / 1024.0)}MB / ${String.format("%.1f", totalSize / 1024.0 / 1024.0)}MB · $speedText"
                                                } else {
                                                    task.progress = -1f
                                                    task.status = "${candidate.name} ${String.format("%.1f", downloaded / 1024.0 / 1024.0)}MB · $speedText"
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            if (!tmpFile.exists() || tmpFile.length() == 0L) throw Exception("下载文件为空")
                            if (totalSize > 0L && tmpFile.length() != totalSize) {
                                throw Exception("文件不完整：${tmpFile.length()}/$totalSize")
                            }
                            if (looksLikeErrorPayload(tmpFile)) {
                                throw Exception("服务器返回了错误内容（${tmpFile.length()}B）")
                            }
                            if (expectedZip && !isUsableZip(tmpFile)) {
                                throw Exception("返回内容不是有效ZIP（${tmpFile.length()}B）")
                            }

                            success = true
                            downloadedFrom = candidate.name

                            withContext(Dispatchers.Main) {
                                task.progress = 1f
                                task.status = "下载完成（${candidate.name}）"
                            }
                            break@candidateLoop
                        } catch (e: LowSpeedFallbackException) {
                            lastErrorMsg = "${candidate.name}: ${e.message}"
                            jumpDirectlyToCnb = true
                            tmpFile.delete()

                            withContext(Dispatchers.Main) {
                                task.progress = 0f
                                task.status = "🐢 ${candidate.name}仅${e.speedKbps}KB/s，直接切换CNB..."
                            }
                            break@attemptLoop
                        } catch (e: SocketTimeoutException) {
                            lastErrorMsg = "${candidate.name}: 读取超时"
                            tmpFile.delete()

                            if (monitorLowSpeed) {
                                jumpDirectlyToCnb = true
                                withContext(Dispatchers.Main) {
                                    task.progress = 0f
                                    task.status = "🐢 ${candidate.name}长时间无数据，直接切换CNB..."
                                }
                                break@attemptLoop
                            }

                            withContext(Dispatchers.Main) {
                                task.progress = 0f
                                task.status = "⚠️ $lastErrorMsg"
                            }
                            if (attempt < 2) delay(700)
                        } catch (e: Exception) {
                            lastErrorMsg = "${candidate.name}: ${e.message ?: "网络异常"}"
                            tmpFile.delete()

                            withContext(Dispatchers.Main) {
                                task.progress = 0f
                                task.status = "⚠️ $lastErrorMsg"
                            }

                            if (attempt < 2) delay(700)
                        } finally {
                            conn?.disconnect()
                        }
                    }
                }
            }

            if (!success) {
                withContext(Dispatchers.Main) {
                    task.isError = true
                    task.progress = 0f
                    task.status = "❌ 获取文件失败：$lastErrorMsg"
                }
                return@withContext
            }

            withContext(Dispatchers.Main) {
                task.status = if (isUsableZip(tmpFile)) "解压中..." else "部署中..."
                task.progress = -1f
            }

            val extractDir = File(stagingDir, "extracted")
            if (!extractDir.mkdirs() && !extractDir.isDirectory) throw Exception("无法创建解压目录")

            val isZipArchive = isUsableZip(tmpFile)
            if (isZipArchive) {
                val canonicalRoot = extractDir.canonicalFile

                ZipInputStream(tmpFile.inputStream().buffered()).use { zis ->
                    var entry = zis.nextEntry

                    while (entry != null) {
                        val outputFile = File(canonicalRoot, entry.name).canonicalFile
                        val insideRoot = outputFile.path == canonicalRoot.path ||
                            outputFile.path.startsWith(canonicalRoot.path + File.separator)

                        if (!insideRoot) throw Exception("压缩包包含危险路径：${entry.name}")

                        if (entry.isDirectory) {
                            if (!outputFile.mkdirs() && !outputFile.isDirectory) {
                                throw Exception("无法创建目录：${entry.name}")
                            }
                        } else {
                            outputFile.parentFile?.let { parent ->
                                if (!parent.mkdirs() && !parent.isDirectory) throw Exception("无法创建目录：${parent.name}")
                            }
                            FileOutputStream(outputFile).buffered().use { output -> zis.copyTo(output) }
                        }

                        zis.closeEntry()
                        entry = zis.nextEntry
                    }
                }
            } else {
                tmpFile.copyTo(File(extractDir, sanitizedFileName(task.url)), overwrite = true)
            }

            var realSrcDir = extractDir
            val subFiles = extractDir.listFiles()
            if (subFiles != null && subFiles.size == 1 && subFiles[0].isDirectory) {
                realSrcDir = subFiles[0]
            }

            val excludeRegexList = rules.mapNotNull {
                try {
                    Regex(it)
                } catch (_: Exception) {
                    null
                }
            }
            val isDict = task.url.contains("dicts", true)

            var successCount = 0
            val errorList = mutableListOf<String>()

            // 混合多目标：稳定的 SAF 目标优先，依赖全盘权限的 /rime 最后执行。
            val orderedTargetPaths = targetPaths
                .map { it.trim() }
                .filter { it.isNotBlank() }
                .distinct()
                .sortedBy { if (it == "DEFAULT") 1 else 0 }

            for ((index, pathStr) in orderedTargetPaths.withIndex()) {
                val pathName = deployPathDisplayName(pathStr)

                try {
                    if (index > 0) delay(300)

                    withContext(Dispatchers.Main) {
                        task.status = "部署 $pathName ${index + 1}/${orderedTargetPaths.size}（$downloadedFrom）..."
                    }

                    if (pathStr == "DEFAULT") {
                        if (!canWriteDefaultRime()) {
                            throw Exception("缺少所有文件访问权限，已跳过")
                        }

                        val root = File(Environment.getExternalStorageDirectory(), "rime")
                        val target = if (isDict) File(root, "dicts") else root
                        copyNormal(realSrcDir, target, excludeRegexList)
                    } else {
                        val targetUri = Uri.parse(pathStr)
                        val rootDoc = DocumentFile.fromTreeUri(context, targetUri)
                            ?: throw Exception("授权目录已失效")

                        if (!rootDoc.exists() || !rootDoc.canWrite()) {
                            throw Exception("SAF授权已失效或目录不可写")
                        }

                        var targetDoc = rootDoc
                        if (isDict) {
                            targetDoc = rootDoc.findFile("dicts")
                                ?: rootDoc.createDirectory("dicts")
                                ?: rootDoc.findFile("dicts")
                                ?: throw Exception("SAF底层拒绝创建dicts目录")
                        }

                        copySaf(context, realSrcDir, targetDoc, excludeRegexList)
                    }

                    successCount++
                } catch (e: Exception) {
                    errorList.add("$pathName(${e.message ?: e.javaClass.simpleName})")
                }
            }

            withContext(Dispatchers.Main) {
                when {
                    successCount == orderedTargetPaths.size && orderedTargetPaths.isNotEmpty() -> {
                        task.isFinished = true
                        task.progress = 1f
                        task.status = "✅ 解压完成（$downloadedFrom）"
                    }
                    successCount > 0 -> {
                        task.isFinished = true
                        task.progress = 1f
                        task.status = "⚠️ 部分完成 [失败: ${errorList.joinToString()}]"
                    }
                    else -> {
                        task.isError = true
                        task.progress = 0f
                        task.status = "❌ 全部解压失败 [${errorList.joinToString()}]"
                    }
                }
            }
        } catch (e: Exception) {
            withContext(Dispatchers.Main) {
                task.isError = true
                task.progress = 0f
                task.status = "❌ 解压失败：${e.message ?: e.javaClass.simpleName}"
            }
        } finally {
            stagingDir.deleteRecursively()
        }
    }
}

fun copyNormal(src: File, dest: File, rules: List<Regex>, currentPath: String = "") {
    if (!dest.exists() && !dest.mkdirs()) {
        throw Exception("无法创建目标目录：${dest.absolutePath}")
    }
    if (!dest.isDirectory) {
        throw Exception("目标路径不是目录：${dest.absolutePath}")
    }
    src.listFiles()?.forEach { file ->
        val relPath = if (currentPath.isEmpty()) file.name else "$currentPath/${file.name}"
        val targetFile = File(dest, file.name)
        
        if (rules.any { it.containsMatchIn(relPath) } && targetFile.exists()) {
            return@forEach
        }
        
        if (file.isDirectory) {
            copyNormal(file, targetFile, rules, relPath)
        } else {
            if (targetFile.exists()) {
                targetFile.delete()
            }
            file.copyTo(targetFile, overwrite = true)
        }
    }
}

fun copySaf(context: Context, src: File, dest: DocumentFile, rules: List<Regex>, currentPath: String = "") {
    src.listFiles()?.forEach { file ->
        val relPath = if (currentPath.isEmpty()) file.name else "$currentPath/${file.name}"
        
        if (rules.any { it.containsMatchIn(relPath) } && dest.findFile(file.name) != null) {
            return@forEach
        }
        
        if (file.isDirectory) {
            var nextDest = dest.findFile(file.name)
            if (nextDest == null) {
                nextDest = dest.createDirectory(file.name)
                if (nextDest == null) nextDest = dest.findFile(file.name)
            }
            if (nextDest != null) {
                copySaf(context, file, nextDest, rules, relPath)
            } else {
                throw Exception("系统锁定了目录:${file.name}")
            }
        } else {
            val existingFile = dest.findFile(file.name)
            if (existingFile != null && existingFile.exists()) {
                existingFile.delete() 
            }
            
            var newDoc = dest.createFile("*/*", file.name)
            if (newDoc == null) newDoc = dest.findFile(file.name)
            
            if (newDoc != null) {
                context.contentResolver.openOutputStream(newDoc.uri, "wt")?.use { out -> 
                    file.inputStream().use { it.copyTo(out) } 
                } ?: throw Exception("文件流被占用拒绝写入:${file.name}")
            } else {
                throw Exception("文件冲突无法创建:${file.name}")
            }
        }
    }
}