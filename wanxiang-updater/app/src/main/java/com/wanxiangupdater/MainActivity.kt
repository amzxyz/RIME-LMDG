package com.wanxiangupdater

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.documentfile.provider.DocumentFile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.atomic.AtomicLong
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

private const val WANXIANG_DEBUG_TAG = "WanxiangUpdater"
private const val DOWNLOAD_SOURCE_CNB = "CNB"
private const val DOWNLOAD_SOURCE_GITHUB = "GitHub"
private const val GITHUB_SHORT_REQUEST_BYTES = 4

class TaskState(
    val title: String,
    val url: String,
    val githubProbeUrl: String? = null
) {
    var progress by mutableStateOf(0f)
    var status by mutableStateOf("等待中...")
    var isFinished by mutableStateOf(false)
    var isError by mutableStateOf(false)

    private val debugQueue = ConcurrentLinkedQueue<String>()
    var debugText by mutableStateOf("")
    var showDebug by mutableStateOf(false)

    fun appendDebug(message: String, error: Throwable? = null) {
        val time = SimpleDateFormat("HH:mm:ss.SSS", Locale.getDefault()).format(Date())
        debugQueue.add("[$time] $message")

        if (error == null) {
            Log.d(WANXIANG_DEBUG_TAG, "$title | $message")
        } else {
            Log.e(WANXIANG_DEBUG_TAG, "$title | $message", error)
        }
    }

    fun debugSnapshot(): String = debugQueue.joinToString("\n")
}

suspend fun publishTaskDebug(task: TaskState) {
    val snapshot = task.debugSnapshot()
    withContext(Dispatchers.Main) { task.debugText = snapshot }
}

@Composable
fun TaskDebugPanel(task: TaskState) {
    val context = LocalContext.current
    if (task.debugText.isBlank()) return

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.End,
        verticalAlignment = Alignment.CenterVertically
    ) {
        TextButton(
            onClick = { task.showDebug = !task.showDebug },
            contentPadding = PaddingValues(horizontal = 6.dp, vertical = 0.dp)
        ) {
            Text(
                if (task.showDebug) "收起日志" else "查看日志",
                fontSize = 10.sp,
                color = MorandiDarkGreen
            )
        }

        TextButton(
            onClick = {
                val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clipboard.setPrimaryClip(ClipData.newPlainText("万象更新调试日志", task.debugText))
                Toast.makeText(context, "调试日志已复制", Toast.LENGTH_SHORT).show()
            },
            contentPadding = PaddingValues(horizontal = 6.dp, vertical = 0.dp)
        ) {
            Text("复制日志", fontSize = 10.sp, color = Color.Gray)
        }
    }

    AnimatedVisibility(visible = task.showDebug) {
        Surface(
            color = Color(0xFFF7F7F7),
            shape = RoundedCornerShape(6.dp),
            modifier = Modifier.fillMaxWidth().heightIn(max = 220.dp)
        ) {
            SelectionContainer {
                Text(
                    task.debugText,
                    fontSize = 10.sp,
                    color = Color.DarkGray,
                    modifier = Modifier.padding(8.dp).verticalScroll(rememberScrollState())
                )
            }
        }
    }
}

const val DEPLOY_PATHS_JSON_KEY = "deploy_paths_json"

/** Root 绝对路径目标的前缀：`ROOT:/data/data/xxx/...` */
const val ROOT_PATH_PREFIX = "ROOT:"

/** 判断路径字符串是否为 root 绝对路径目标。 */
fun isRootTarget(path: String): Boolean = path.startsWith(ROOT_PATH_PREFIX)

/** 从 ROOT: 前缀路径中取出绝对路径。 */
fun rootTargetPath(path: String): String = path.removePrefix(ROOT_PATH_PREFIX).trim()

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
    if (isRootTarget(path)) {
        return rootTargetPath(path).substringAfterLast("/").ifBlank { "root目录" }
    }

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

fun probeSafTreeWriteAccess(context: Context, uri: Uri): String? {
    val rootDoc = runCatching { DocumentFile.fromTreeUri(context, uri) }.getOrNull()
        ?: return "无法解析SAF目录"

    val probeName = "wanxiang_write_probe_${UUID.randomUUID()}.tmp"
    val probeDoc = try {
        rootDoc.createFile("application/octet-stream", probeName)
    } catch (error: Exception) {
        return "SAF创建探测文件失败：${error.javaClass.simpleName}: ${error.message ?: "无详细信息"}"
    } ?: return "SAF创建探测文件失败"

    try {
        context.contentResolver.openOutputStream(probeDoc.uri, "w")?.use { output ->
            output.write(byteArrayOf(0x57))
            output.flush()
        } ?: return "SAF无法打开探测文件写入流"
    } catch (error: Exception) {
        return "SAF写入探测失败：${error.javaClass.simpleName}: ${error.message ?: "无详细信息"}"
    }

    if (!runCatching { probeDoc.delete() }.getOrDefault(false)) {
        return "SAF探测文件写入成功，但删除失败"
    }
    return null
}

fun hasSafTarget(targetPaths: List<String>): Boolean {
    return targetPaths.any { it.trim().isNotBlank() && it.trim() != "DEFAULT" }
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

data class GithubApiResult(
    val json: String? = null,
    val responseCode: Int? = null,
    val error: String = ""
)

suspend fun fetchGithubApiJson(apiUrl: String, token: String): GithubApiResult = withContext(Dispatchers.IO) {
    var conn: HttpURLConnection? = null
    try {
        conn = URL(apiUrl).openConnection() as HttpURLConnection
        conn.instanceFollowRedirects = true
        conn.connectTimeout = 8000
        conn.readTimeout = 12000
        conn.setRequestProperty("User-Agent", "WanxiangUpdater-Android")
        conn.setRequestProperty("Accept", "application/vnd.github+json, application/json")
        if (token.isNotBlank()) conn.setRequestProperty("Authorization", "Bearer ${token.trim()}")

        val code = conn.responseCode
        if (code !in 200..299) {
            return@withContext GithubApiResult(responseCode = code, error = "HTTP $code")
        }

        val content = conn.inputStream.bufferedReader().use { it.readText() }.trim()
        if (!content.startsWith("{") && !content.startsWith("[")) {
            return@withContext GithubApiResult(responseCode = code, error = "返回内容不是JSON")
        }

        GithubApiResult(json = content, responseCode = code)
    } catch (error: Exception) {
        GithubApiResult(error = error.message ?: error.javaClass.simpleName)
    } finally {
        conn?.disconnect()
    }
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

/**
 * CNB 被选为实际下载源时，向对应的 GitHub Release 地址发送一次极短 GET 请求。
 * 只读取前 4 字节后立即关闭，所有异常完全吞掉；不写任务日志、不改变界面状态，
 * 也不影响随后进行的 CNB 下载。Token 只会发给 github.com。
 */
suspend fun silentGithubShortDownloadRequest(githubUrl: String, token: String) = withContext(Dispatchers.IO) {
    var currentUrl = githubUrl
    var redirectCount = 0

    try {
        while (redirectCount < 5) {
            var conn: HttpURLConnection? = null
            try {
                val url = URL(currentUrl)
                conn = url.openConnection() as HttpURLConnection
                conn.instanceFollowRedirects = false
                conn.requestMethod = "GET"
                conn.connectTimeout = 5000
                conn.readTimeout = 5000
                conn.setRequestProperty("User-Agent", "WanxiangUpdater-Android")
                conn.setRequestProperty("Range", "bytes=0-${GITHUB_SHORT_REQUEST_BYTES - 1}")
                conn.setRequestProperty("Accept-Encoding", "identity")
                if (url.host.equals("github.com", true) && token.isNotBlank()) {
                    conn.setRequestProperty("Authorization", "Bearer ${token.trim()}")
                }

                val code = conn.responseCode
                if (code in listOf(301, 302, 303, 307, 308)) {
                    val location = conn.getHeaderField("Location")
                    if (location.isNullOrBlank()) return@withContext
                    currentUrl = if (location.startsWith("http")) location else URL(url, location).toString()
                    redirectCount++
                    continue
                }

                if (code in 200..299) {
                    conn.inputStream.use { input ->
                        val buffer = ByteArray(GITHUB_SHORT_REQUEST_BYTES)
                        var offset = 0
                        while (offset < buffer.size) {
                            val count = input.read(buffer, offset, buffer.size - offset)
                            if (count < 0) break
                            offset += count
                        }
                    }
                }
                return@withContext
            } finally {
                conn?.disconnect()
            }
        }
    } catch (_: Exception) {
        // 必须静默：CNB 下载不能因 GitHub 短请求失败而受影响。
    }
}

// --- 自定义模式数据模型与存储助手 ---
data class CustomTask(
    val id: String,
    var name: String,
    var url: String,
    var boundPath: String,
    var isSelected: Boolean = false,
    var isExpanded: Boolean = true
)

fun loadCustomTasks(jsonStr: String): List<CustomTask> {
    val list = mutableListOf<CustomTask>()
    try {
        val array = org.json.JSONArray(jsonStr)
        for (i in 0 until array.length()) {
            val obj = array.getJSONObject(i)
            list.add(
                CustomTask(
                    id = obj.optString("id", UUID.randomUUID().toString()),
                    name = obj.optString("name", ""),
                    url = obj.optString("url", ""),
                    boundPath = obj.optString("boundPath", "DEFAULT"),
                    isSelected = obj.optBoolean("isSelected", false),
                    isExpanded = obj.optBoolean("isExpanded", true)
                )
            )
        }
    } catch (error: Exception) {
        Log.e(WANXIANG_DEBUG_TAG, "读取自定义任务失败", error)
    }
    return list
}

fun saveCustomTasks(tasks: List<CustomTask>, sharedPref: android.content.SharedPreferences) {
    val array = org.json.JSONArray()
    tasks.forEach {
        array.put(org.json.JSONObject().apply {
            put("id", it.id)
            put("name", it.name)
            put("url", it.url)
            put("boundPath", it.boundPath)
            put("isSelected", it.isSelected)
            put("isExpanded", it.isExpanded)
        })
    }
    sharedPref.edit().putString("custom_tasks_data", array.toString()).apply()
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(
                colorScheme = lightColorScheme(
                    primary = MorandiGreen,
                    onPrimary = Color.White,
                    secondaryContainer = MorandiLightGreen,
                    outline = MorandiBorder
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

    val localVersionName = remember {
        try {
            context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "1.0"
        } catch (_: Exception) {
            "1.0"
        }
    }

    var showPermissionDialog by remember { mutableStateOf(false) }

    // Root 绝对路径目标：输入对话框状态（对话框本体在 savedPaths 声明之后）
    var showRootPathDialog by remember { mutableStateOf(false) }
    var rootPathInput by remember { mutableStateOf("") }
    var rootAvailable by remember { mutableStateOf<Boolean?>(null) }

    LaunchedEffect(showRootPathDialog) {
        if (showRootPathDialog && rootAvailable == null) {
            rootAvailable = withContext(Dispatchers.IO) { RootShell.isAvailable() }
        }
    }

    if (showPermissionDialog) {
        AlertDialog(
            onDismissRequest = {},
            title = {
                Text(
                    "需要存储访问权限",
                    fontWeight = FontWeight.Bold,
                    fontSize = 18.sp,
                    color = MorandiDarkGreen
                )
            },
            text = {
                Text(
                    text = "该权限仅用于写入手机根目录的 /rime。\n\n" +
                        "小企鹅目录使用独立的 SAF 授权，不受此权限影响。存在小企鹅目标时，本次更新会继续，只跳过 /rime。",
                    fontSize = 14.sp,
                    lineHeight = 20.sp,
                    color = Color.DarkGray
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
                    Text("稍后授权", color = Color.Gray)
                }
            },
            containerColor = Color.White
        )
    }

    var isPro by remember { mutableStateOf(sharedPref.getBoolean("is_pro", true)) }
    var auxScheme by remember { mutableStateOf(sharedPref.getString("aux_scheme", "zrm") ?: "zrm") }
    var updateChannel by remember { mutableStateOf(sharedPref.getString("update_channel", "Stable") ?: "Stable") }
    var downloadSource by remember {
        mutableStateOf(sharedPref.getString("download_source", DOWNLOAD_SOURCE_CNB) ?: DOWNLOAD_SOURCE_CNB)
    }
    var githubToken by remember { mutableStateOf(sharedPref.getString("gh_token", "") ?: "") }

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

    if (showRootPathDialog) {
        AlertDialog(
            onDismissRequest = {
                showRootPathDialog = false
                rootPathInput = ""
            },
            title = {
                Text(
                    "🔓 添加 Root 目标目录",
                    fontWeight = FontWeight.Bold,
                    fontSize = 18.sp,
                    color = MorandiDarkGreen
                )
            },
            text = {
                Column {
                    Text(
                        "输入手机上的绝对路径（如 /data/data/某应用/files/rime）。需要设备已 root，且授予该应用 root 权限。",
                        fontSize = 13.sp,
                        lineHeight = 19.sp,
                        color = Color.DarkGray
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                    OutlinedTextField(
                        value = rootPathInput,
                        onValueChange = { rootPathInput = it },
                        label = { Text("绝对路径", fontSize = 12.sp) },
                        placeholder = { Text("/data/data/...", fontSize = 12.sp) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = when (rootAvailable) {
                            null -> "正在检测 root..."
                            true -> "✅ 已检测到 root 权限"
                            false -> "⚠️ 未检测到 root，添加后部署会失败"
                        },
                        fontSize = 12.sp,
                        color = when (rootAvailable) {
                            true -> MorandiGreen
                            false -> Color(0xFFC46A6A)
                            null -> Color.Gray
                        }
                    )
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        val trimmed = rootPathInput.trim()
                        if (trimmed.isBlank()) return@Button
                        val pathStr = "$ROOT_PATH_PREFIX$trimmed"
                        val newPaths = (savedPaths + pathStr).distinct()
                        savedPaths = newPaths
                        saveDeployPaths(newPaths, sharedPref)
                        showRootPathDialog = false
                        rootPathInput = ""
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = MorandiGreen)
                ) {
                    Text("添加", fontWeight = FontWeight.Bold)
                }
            },
            dismissButton = {
                TextButton(onClick = {
                    showRootPathDialog = false
                    rootPathInput = ""
                }) {
                    Text("取消", color = Color.Gray)
                }
            },
            containerColor = Color.White
        )
    }

    fun ensureDeployTargetsReady(targetPaths: List<String>): Boolean {
        val normalized = targetPaths.map { it.trim() }.filter { it.isNotBlank() }.distinct()
        if (normalized.isEmpty()) return false

        if ("DEFAULT" in normalized && !canWriteDefaultRime()) {
            showPermissionDialog = true
            return hasSafTarget(normalized)
        }
        return true
    }

    var latestStableTag by remember { mutableStateOf("v1.0.0") }
    var cloudVersionName by remember { mutableStateOf("") }
    var updaterDownloadUrl by remember { mutableStateOf("") }
    var updateCheckSource by remember { mutableStateOf("") }
    var isCheckingUpdate by remember { mutableStateOf(true) }
    var updateCheckNonce by remember { mutableStateOf(0) }
    var githubApiHint by remember { mutableStateOf("") }

    // 正式版标签：官方 GitHub API 静默请求；失败时仍保留 CNB 标签兜底。
    LaunchedEffect(githubToken, updateCheckNonce) {
        githubApiHint = ""
        var detectedStableTag: String? = null

        val mainResult = fetchGithubApiJson(
            "https://api.github.com/repos/amzxyz/rime-wanxiang/releases/latest",
            githubToken
        )

        if (!mainResult.json.isNullOrBlank()) {
            detectedStableTag = runCatching {
                org.json.JSONObject(mainResult.json)
                    .optString("tag_name")
                    .ifBlank { null }
            }.getOrNull()
        }

        if (mainResult.responseCode in listOf(403, 429)) {
            githubApiHint = if (githubToken.isBlank()) {
                "GitHub 匿名 IP 请求额度已耗尽，请填写自己的 Token 后重新检测。"
            } else {
                "当前 Token 暂时无法通过 GitHub API 校验，请检查 Token 权限或稍后重试。"
            }
        } else if (mainResult.json == null && mainResult.error.isNotBlank()) {
            githubApiHint = "GitHub API 暂时无法连接，下载仍可按当前来源继续。"
        }

        if (detectedStableTag == null) {
            detectedStableTag = findLatestStableCnbTag(fetchCnbReleases("rime-wanxiang"))
        }

        detectedStableTag?.let { latestStableTag = it }
    }

    // 更新器自身检测：只直连 GitHub 官方 API；失败仅显示可读提示。
    LaunchedEffect(updateCheckNonce, githubToken) {
        isCheckingUpdate = true
        updateCheckSource = ""
        cloudVersionName = ""
        updaterDownloadUrl = ""

        val result = withContext(Dispatchers.IO) {
            val apiResult = fetchGithubApiJson(
                "https://api.github.com/repos/amzxyz/RIME-LMDG/releases/tags/tool",
                githubToken
            )

            if (apiResult.json.isNullOrBlank()) {
                val sourceText = when {
                    apiResult.responseCode in listOf(403, 429) && githubToken.isBlank() ->
                        "匿名 IP 额度已耗尽，请填写 GitHub Token"
                    apiResult.responseCode in listOf(403, 429) ->
                        "GitHub Token 请求受限"
                    else -> "GitHub 官方 API 连接失败"
                }
                return@withContext Triple("", "", sourceText)
            }

            val assets = runCatching {
                org.json.JSONObject(apiResult.json).optJSONArray("assets")
            }.getOrNull() ?: return@withContext Triple("", "", "GitHub官方API未发现资源")

            for (i in 0 until assets.length()) {
                val asset = assets.optJSONObject(i) ?: continue
                val name = asset.optString("name")

                if (name.startsWith("Wanxiang-Updater-Android") && name.endsWith(".apk", true)) {
                    val downloadUrl = asset.optString("browser_download_url")
                    val version = Regex(
                        """Wanxiang-Updater-Android.*?(\d+\.\d+(?:\.\d+)?)"""
                    ).find(name)?.groupValues?.get(1).orEmpty()
                    return@withContext Triple(version, downloadUrl, "GitHub官方API")
                }
            }

            Triple("", "", "GitHub官方API未发现更新包")
        }

        cloudVersionName = result.first
        updaterDownloadUrl = result.second
        updateCheckSource = result.third
        isCheckingUpdate = false
    }

    var isMainDownloading by remember { mutableStateOf(false) }
    var mainActiveTasks by remember { mutableStateOf<List<TaskState>>(emptyList()) }
    var customActiveTasks by remember { mutableStateOf<List<TaskState>>(emptyList()) }

    val auxMap = mapOf(
        "zrm" to "自然码",
        "wx" to "万象",
        "flypy" to "小鹤",
        "moqi" to "墨奇",
        "hanxin" to "汉心",
        "shouyou" to "首右",
        "shyplus" to "首右+",
        "tiger" to "虎码",
        "wubi" to "五笔"
    )

    var selectedTabIndex by remember { mutableStateOf(0) }
    var customTasks by remember {
        mutableStateOf(loadCustomTasks(sharedPref.getString("custom_tasks_data", "[]") ?: "[]"))
    }

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
            Column(
                modifier = Modifier
                    .padding(16.dp)
                    .verticalScroll(rememberScrollState())
                    .weight(1f)
            ) {
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
                            val hasNewVersion = !isCheckingUpdate && cloudVersionName.isNotEmpty() &&
                                isRemoteVersionNewer(cloudVersionName, localVersionName)
                            Text("🔧 更新器自身检测", fontWeight = FontWeight.Bold, color = Color.DarkGray, fontSize = 14.sp)
                            Text(
                                text = when {
                                    isCheckingUpdate -> "正在通过GitHub检测..."
                                    cloudVersionName.isEmpty() -> updateCheckSource.ifBlank { "GitHub未发现有效更新包" }
                                    hasNewVersion -> "发现新版本: v$cloudVersionName"
                                    else -> "已是最新版本"
                                },
                                fontSize = 12.sp,
                                color = if (hasNewVersion) MorandiGreen else Color.Gray
                            )
                            if (!isCheckingUpdate && cloudVersionName.isNotEmpty()) {
                                Text("软件检测：$updateCheckSource", fontSize = 10.sp, color = Color.Gray)
                            }
                        }

                        val hasNewVersion = !isCheckingUpdate && cloudVersionName.isNotEmpty() &&
                            isRemoteVersionNewer(cloudVersionName, localVersionName)
                        Column(horizontalAlignment = Alignment.End) {
                            Button(
                                onClick = {
                                    if (updaterDownloadUrl.isNotBlank()) {
                                        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(updaterDownloadUrl)))
                                    }
                                },
                                enabled = hasNewVersion,
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = if (hasNewVersion) MorandiGreen else Color.LightGray
                                ),
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
                            Text(
                                "⚠️ 未配置任何目标路径，将无法解压文件！",
                                fontSize = 12.sp,
                                color = Color.Red,
                                modifier = Modifier.padding(bottom = 8.dp)
                            )
                        }

                        savedPaths.forEach { pathStr ->
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)
                            ) {
                                Text(
                                    text = when {
                                        pathStr == "DEFAULT" -> "🎯 默认: 手机根目录 /rime"
                                        isRootTarget(pathStr) -> "🔓 Root: ${rootTargetPath(pathStr)}"
                                        else -> "🎯 授权: ${Uri.decode(pathStr).substringAfterLast(":")}"
                                    },
                                    fontSize = 13.sp,
                                    color = Color.DarkGray,
                                    modifier = Modifier.weight(1f),
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis
                                )
                                TextButton(
                                    onClick = {
                                        if (pathStr != "DEFAULT" && !isRootTarget(pathStr)) {
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
                            OutlinedButton(
                                onClick = { showRootPathDialog = true },
                                modifier = Modifier.weight(1f).height(36.dp)
                            ) {
                                Text("🔓 添加 Root 目录", fontSize = 12.sp)
                            }
                            if (!savedPaths.contains("DEFAULT")) {
                                TextButton(
                                    onClick = {
                                        val newPaths = (savedPaths + "DEFAULT").distinct()
                                        savedPaths = newPaths
                                        saveDeployPaths(newPaths, sharedPref)
                                        if (!canWriteDefaultRime()) showPermissionDialog = true
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

                Card(
                    colors = CardDefaults.cardColors(containerColor = Color.White),
                    border = CardDefaults.outlinedCardBorder(true),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.fillMaxWidth()) {
                        TextButton(
                            onClick = { showAdvancedRules = !showAdvancedRules },
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp)
                        ) {
                            Text(
                                if (showAdvancedRules) "▼ 收起护盾配置" else "▶ 展开防覆盖保护配置 (高级)",
                                color = MorandiDarkGreen,
                                fontWeight = FontWeight.Bold
                            )
                        }
                        AnimatedVisibility(visible = showAdvancedRules) {
                            Column(modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 16.dp)) {
                                Text(
                                    "相对路径命中正则且本地已有该文件，强制跳过覆盖：",
                                    fontSize = 11.sp,
                                    color = Color.Gray,
                                    modifier = Modifier.padding(bottom = 8.dp)
                                )
                                OutlinedTextField(
                                    value = excludeRulesText,
                                    onValueChange = {
                                        excludeRulesText = it
                                        sharedPref.edit().putString("exclude_rules", it).apply()
                                    },
                                    modifier = Modifier.fillMaxWidth().height(160.dp),
                                    textStyle = androidx.compose.ui.text.TextStyle(
                                        fontSize = 12.sp,
                                        fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace
                                    )
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

                // 恢复旧版 CNB / GitHub 双入口，彻底移除代理路线与测速逻辑。
                Card(
                    colors = CardDefaults.cardColors(containerColor = Color.White),
                    border = CardDefaults.outlinedCardBorder(true),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text("🌐 下载源配置", fontWeight = FontWeight.Bold, color = Color.DarkGray)
                        Text(
                            "选择哪个来源就直接从哪个来源下载，不再经过代理或自动切换。",
                            fontSize = 11.sp,
                            color = Color.Gray
                        )

                        Row(verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(
                                selected = downloadSource == DOWNLOAD_SOURCE_CNB,
                                onClick = {
                                    downloadSource = DOWNLOAD_SOURCE_CNB
                                    sharedPref.edit().putString("download_source", DOWNLOAD_SOURCE_CNB).apply()
                                }
                            )
                            Text("CNB", fontSize = 14.sp)
                            Spacer(modifier = Modifier.width(12.dp))
                            RadioButton(
                                selected = downloadSource == DOWNLOAD_SOURCE_GITHUB,
                                onClick = {
                                    downloadSource = DOWNLOAD_SOURCE_GITHUB
                                    sharedPref.edit().putString("download_source", DOWNLOAD_SOURCE_GITHUB).apply()
                                }
                            )
                            Text("GitHub", fontSize = 14.sp)
                        }

                        OutlinedTextField(
                            value = githubToken,
                            onValueChange = {
                                githubToken = it
                                sharedPref.edit().putString("gh_token", it).apply()
                            },
                            label = { Text("GitHub Token（建议填写）", fontSize = 12.sp) },
                            supportingText = {
                                Text(
                                    githubApiHint.ifBlank {
                                        "选择GitHub时，匿名 IP 的请求额度可能被多人共享并耗尽，请填写Token。"
                                    },
                                    fontSize = 10.sp,
                                    color = if (githubApiHint.contains("耗尽") || githubApiHint.contains("受限")) {
                                        Color(0xFFC46A6A)
                                    } else {
                                        Color.Gray
                                    }
                                )
                            },
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

                val githubSchemaUrl = "https://github.com/amzxyz/rime-wanxiang/releases/download/$githubSchemaTag/$schemaFileName"
                val githubDictUrl = "https://github.com/amzxyz/rime-wanxiang/releases/download/dict-nightly/$dictFileName"
                val githubModelUrl = "https://github.com/amzxyz/RIME-LMDG/releases/download/LTS/wanxiang-lts-zh-hans.gram"

                val cnbSchemaUrl = "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/$cnbSchemaTag/$schemaFileName"
                val cnbDictUrl = "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/v1.0.0/$dictFileName"
                val cnbModelUrl = "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/model/wanxiang-lts-zh-hans.gram"

                val schemaUrl = if (downloadSource == DOWNLOAD_SOURCE_CNB) cnbSchemaUrl else githubSchemaUrl
                val dictUrl = if (downloadSource == DOWNLOAD_SOURCE_CNB) cnbDictUrl else githubDictUrl
                val modelUrl = if (downloadSource == DOWNLOAD_SOURCE_CNB) cnbModelUrl else githubModelUrl

                // 仅 CNB 模式使用：实际下载前向对应 GitHub 资源发 4 字节静默 GET。
                val githubProbeUrls = if (downloadSource == DOWNLOAD_SOURCE_CNB) {
                    mapOf(
                        cnbSchemaUrl to githubSchemaUrl,
                        cnbDictUrl to githubDictUrl,
                        cnbModelUrl to githubModelUrl
                    )
                } else {
                    emptyMap()
                }

                val tasksMap = listOf(
                    "🚀 全量更新" to listOf(schemaUrl, dictUrl, modelUrl),
                    "⚙️ 仅方案" to listOf(schemaUrl),
                    "📖 仅词库" to listOf(dictUrl),
                    "🧠 仅模型" to listOf(modelUrl)
                )

                Card(
                    colors = CardDefaults.cardColors(containerColor = Color.White),
                    border = CardDefaults.outlinedCardBorder(true),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text("🚀 更新通道", fontWeight = FontWeight.Bold, color = Color.DarkGray)
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(
                                selected = updateChannel == "Stable",
                                onClick = {
                                    updateChannel = "Stable"
                                    sharedPref.edit().putString("update_channel", "Stable").apply()
                                }
                            )
                            Text("正式版 (${latestStableTag})", fontSize = 14.sp)
                            Spacer(modifier = Modifier.width(16.dp))
                            RadioButton(
                                selected = updateChannel == "Preview",
                                onClick = {
                                    updateChannel = "Preview"
                                    sharedPref.edit().putString("update_channel", "Preview").apply()
                                }
                            )
                            Text("预览版", fontSize = 14.sp, color = MorandiGreen)
                        }

                        Divider(color = MorandiLightGreen, modifier = Modifier.padding(vertical = 8.dp))
                        Text("📦 方案版本", fontWeight = FontWeight.Bold, color = Color.DarkGray)
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(
                                selected = isPro,
                                onClick = {
                                    isPro = true
                                    sharedPref.edit().putBoolean("is_pro", true).apply()
                                }
                            )
                            Text("Pro版", fontSize = 14.sp)
                            Spacer(modifier = Modifier.width(16.dp))
                            RadioButton(
                                selected = !isPro,
                                onClick = {
                                    isPro = false
                                    sharedPref.edit().putBoolean("is_pro", false).apply()
                                }
                            )
                            Text("Base版", fontSize = 14.sp)
                        }

                        if (isPro) {
                            Divider(color = MorandiLightGreen, modifier = Modifier.padding(vertical = 8.dp))
                            Text(
                                "⌨️ 辅助类型：",
                                fontWeight = FontWeight.Bold,
                                color = Color.DarkGray,
                                fontSize = 13.sp,
                                modifier = Modifier.padding(bottom = 4.dp)
                            )

                            FlowRow(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                auxMap.forEach { (key, name) ->
                                    FilterChip(
                                        selected = auxScheme == key,
                                        onClick = {
                                            auxScheme = key
                                            sharedPref.edit().putString("aux_scheme", key).apply()
                                        },
                                        label = { Text(name, fontSize = 12.sp) }
                                    )
                                }
                            }
                        }


                        Divider(color = MorandiLightGreen, modifier = Modifier.padding(vertical = 12.dp))
                        Text("执行操作:", fontWeight = FontWeight.Bold, color = Color.DarkGray)
                        tasksMap.chunked(2).forEach { rowTasks ->
                            Row(
                                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                rowTasks.forEach { (name, urls) ->
                                    Button(
                                        onClick = {
                                            if (savedPaths.isEmpty()) return@Button
                                            if (!ensureDeployTargetsReady(savedPaths)) return@Button

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
                                                githubProbeUrls = githubProbeUrls
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
                }
                Spacer(modifier = Modifier.height(12.dp))

                AnimatedVisibility(visible = mainActiveTasks.isNotEmpty()) {
                    Card(
                        colors = CardDefaults.cardColors(containerColor = MorandiLightGreen),
                        modifier = Modifier.fillMaxWidth().padding(bottom = 16.dp)
                    ) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Text("📥 任务进度", fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
                            mainActiveTasks.forEach { task ->
                                Column(modifier = Modifier.padding(vertical = 4.dp)) {
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.SpaceBetween
                                    ) {
                                        Text(task.title, fontSize = 12.sp, modifier = Modifier.weight(1f), maxLines = 1)
                                        Text(
                                            task.status,
                                            fontSize = 11.sp,
                                            color = if (task.isError) Color.Red else Color.Gray
                                        )
                                    }
                                    if (task.progress < 0f) {
                                        LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                                    } else {
                                        LinearProgressIndicator(progress = task.progress, modifier = Modifier.fillMaxWidth())
                                    }
                                    TaskDebugPanel(task)
                                }
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
                githubToken = githubToken,
                onRequestAllFilesAccess = { showPermissionDialog = true }
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
    githubToken: String,
    onRequestAllFilesAccess: () -> Unit
) {
    var taskAwaitingPath by remember { mutableStateOf<String?>(null) }
    var showCustomRootDialog by remember { mutableStateOf(false) }
    var customRootInput by remember { mutableStateOf("") }
    val isDownloading = activeTasks.isNotEmpty() && activeTasks.any { !it.isFinished && !it.isError }

    fun ensureCustomTargetsReady(targetPaths: List<String>): Boolean {
        val normalized = targetPaths.map { it.trim() }.filter { it.isNotBlank() }.distinct()
        if (normalized.isEmpty()) return false

        if ("DEFAULT" in normalized && !canWriteDefaultRime()) {
            onRequestAllFilesAccess()
            return hasSafTarget(normalized)
        }
        return true
    }

    if (showCustomRootDialog) {
        AlertDialog(
            onDismissRequest = {
                showCustomRootDialog = false
                customRootInput = ""
                taskAwaitingPath = null
            },
            title = {
                Text(
                    "🔓 输入 Root 目标路径",
                    fontWeight = FontWeight.Bold,
                    fontSize = 18.sp,
                    color = MorandiDarkGreen
                )
            },
            text = {
                Column {
                    Text(
                        "输入手机上的绝对路径（如 /data/data/某应用/files/rime）。需要设备已 root。",
                        fontSize = 13.sp,
                        lineHeight = 19.sp,
                        color = Color.DarkGray
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                    OutlinedTextField(
                        value = customRootInput,
                        onValueChange = { customRootInput = it },
                        label = { Text("绝对路径", fontSize = 12.sp) },
                        placeholder = { Text("/data/data/...", fontSize = 12.sp) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        val trimmed = customRootInput.trim()
                        if (trimmed.isBlank()) return@Button
                        val pathStr = "$ROOT_PATH_PREFIX$trimmed"
                        taskAwaitingPath?.let { taskId ->
                            val updated = customTasks.map { task ->
                                if (task.id == taskId) task.copy(boundPath = pathStr) else task
                            }
                            onTasksChange(updated)
                        }
                        taskAwaitingPath = null
                        showCustomRootDialog = false
                        customRootInput = ""
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = MorandiGreen)
                ) {
                    Text("确定", fontWeight = FontWeight.Bold)
                }
            },
            dismissButton = {
                TextButton(onClick = {
                    showCustomRootDialog = false
                    customRootInput = ""
                    taskAwaitingPath = null
                }) {
                    Text("取消", color = Color.Gray)
                }
            },
            containerColor = Color.White
        )
    }

    val customDirLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            context.contentResolver.takePersistableUriPermission(
                uri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            )
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
            Card(
                colors = CardDefaults.cardColors(containerColor = MorandiLightGreen),
                modifier = Modifier.fillMaxWidth().padding(bottom = 16.dp)
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            if (activeTasks.isNotEmpty()) "📥 实时进度" else "📦 待执行队列",
                            fontWeight = FontWeight.Bold,
                            color = MorandiDarkGreen
                        )

                        if (selectedCount > 0 && !isDownloading) {
                            Button(
                                onClick = {
                                    val targets = customTasks.filter {
                                        it.isSelected && it.url.isNotBlank() && it.boundPath.isNotBlank()
                                    }
                                    if (targets.isEmpty()) return@Button
                                    if (!ensureCustomTargetsReady(targets.map { it.boundPath })) return@Button

                                    coroutineScope.launch {
                                        setDownloading(true)
                                        val uiTasks = targets.map { target ->
                                            val fileName = target.url.substringBefore("?").substringAfterLast("/")
                                            TaskState("${target.name.ifBlank { "未命名" }} ($fileName)", target.url)
                                        }
                                        setTasks(uiTasks)

                                        for ((taskData, uiState) in targets.zip(uiTasks)) {
                                            downloadAndDeployTask(
                                                task = uiState,
                                                token = githubToken,
                                                targetPaths = listOf(taskData.boundPath),
                                                context = context,
                                                rules = emptyList()
                                            )
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
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween
                            ) {
                                Text(
                                    task.title,
                                    fontSize = 12.sp,
                                    modifier = Modifier.weight(1f),
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis
                                )
                                Text(
                                    task.status,
                                    fontSize = 11.sp,
                                    color = if (task.isError) Color.Red else Color.DarkGray
                                )
                            }
                            if (task.progress < 0f) {
                                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                            } else {
                                LinearProgressIndicator(progress = task.progress, modifier = Modifier.fillMaxWidth())
                            }
                            TaskDebugPanel(task)
                        }
                    }
                }
            }
        }

        if (customTasks.isEmpty()) {
            Text(
                "暂无自定义任务，请点击下方添加",
                fontSize = 14.sp,
                color = Color.Gray,
                modifier = Modifier.padding(vertical = 20.dp).align(Alignment.CenterHorizontally)
            )
        }

        customTasks.forEachIndexed { index, task ->
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = if (task.isSelected) Color(0xFFF5F9F6) else Color.White
                ),
                border = BorderStroke(1.dp, if (task.isSelected) MorandiGreen else MorandiBorder),
                modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp)
            ) {
                Column {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable {
                                val updated = customTasks.toMutableList()
                                updated[index] = task.copy(isExpanded = !task.isExpanded)
                                onTasksChange(updated)
                            }
                            .padding(start = 12.dp, end = 12.dp, top = 12.dp, bottom = 12.dp)
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
                                onValueChange = { newName ->
                                    val updated = customTasks.toMutableList()
                                    updated[index] = task.copy(name = newName)
                                    onTasksChange(updated)
                                },
                                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 13.sp, color = Color.DarkGray),
                                singleLine = true,
                                decorationBox = { innerTextField ->
                                    Box(
                                        contentAlignment = Alignment.CenterStart,
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .height(38.dp)
                                            .border(1.dp, MorandiBorder, RoundedCornerShape(6.dp))
                                            .padding(horizontal = 10.dp)
                                    ) {
                                        if (task.name.isEmpty()) Text("如: 极速版扩展包", color = Color.LightGray, fontSize = 13.sp)
                                        innerTextField()
                                    }
                                }
                            )
                            Spacer(modifier = Modifier.height(10.dp))

                            Text("直链 URL 或 绝对路径 (.zip)", fontSize = 11.sp, color = Color.Gray, modifier = Modifier.padding(bottom = 4.dp))
                            androidx.compose.foundation.text.BasicTextField(
                                value = task.url,
                                onValueChange = { newUrl ->
                                    val updated = customTasks.toMutableList()
                                    updated[index] = task.copy(url = newUrl)
                                    onTasksChange(updated)
                                },
                                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 13.sp, color = Color.DarkGray),
                                singleLine = true,
                                decorationBox = { innerTextField ->
                                    Box(
                                        contentAlignment = Alignment.CenterStart,
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .height(38.dp)
                                            .border(1.dp, MorandiBorder, RoundedCornerShape(6.dp))
                                            .padding(horizontal = 10.dp)
                                    ) {
                                        if (task.url.isEmpty()) Text("https://... 或 /storage/...", color = Color.LightGray, fontSize = 13.sp)
                                        innerTextField()
                                    }
                                }
                            )
                            Spacer(modifier = Modifier.height(10.dp))

                            Text("目标解压路径", fontSize = 11.sp, color = Color.Gray, modifier = Modifier.padding(bottom = 4.dp))
                            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                                androidx.compose.foundation.text.BasicTextField(
                                    value = when {
                                        task.boundPath == "DEFAULT" -> "默认: /rime"
                                        isRootTarget(task.boundPath) -> "Root: ${rootTargetPath(task.boundPath)}"
                                        else -> "授权: ${Uri.decode(task.boundPath).substringAfterLast(":")}"
                                    },
                                    onValueChange = {},
                                    readOnly = true,
                                    textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp, color = Color.DarkGray),
                                    singleLine = true,
                                    modifier = Modifier.weight(1f),
                                    decorationBox = { innerTextField ->
                                        Box(
                                            contentAlignment = Alignment.CenterStart,
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .height(38.dp)
                                                .background(Color(0xFFF9F9F9), RoundedCornerShape(6.dp))
                                                .border(1.dp, MorandiBorder, RoundedCornerShape(6.dp))
                                                .padding(horizontal = 10.dp)
                                        ) {
                                            innerTextField()
                                        }
                                    }
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                    Button(
                                        onClick = {
                                            taskAwaitingPath = task.id
                                            customDirLauncher.launch(null)
                                        },
                                        modifier = Modifier.height(38.dp),
                                        shape = RoundedCornerShape(6.dp),
                                        contentPadding = PaddingValues(horizontal = 12.dp),
                                        colors = ButtonDefaults.buttonColors(containerColor = MorandiDarkGreen)
                                    ) {
                                        Text("配置目录", fontSize = 12.sp)
                                    }
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        TextButton(
                                            onClick = {
                                                taskAwaitingPath = task.id
                                                showCustomRootDialog = true
                                            },
                                            modifier = Modifier.height(20.dp),
                                            contentPadding = PaddingValues(horizontal = 4.dp)
                                        ) {
                                            Text("Root", fontSize = 10.sp, color = MorandiDarkGreen)
                                        }
                                        if (task.boundPath != "DEFAULT") {
                                            TextButton(
                                                onClick = {
                                                    val updated = customTasks.toMutableList()
                                                    updated[index] = task.copy(boundPath = "DEFAULT")
                                                    onTasksChange(updated)
                                                },
                                                modifier = Modifier.height(20.dp),
                                                contentPadding = PaddingValues(horizontal = 4.dp)
                                            ) {
                                                Text("重置", fontSize = 10.sp, color = Color.Gray)
                                            }
                                        }
                                    }
                                }
                            }

                            Spacer(modifier = Modifier.height(16.dp))
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                TextButton(
                                    onClick = {
                                        val updated = customTasks.toMutableList()
                                        updated.removeAt(index)
                                        onTasksChange(updated)
                                    }
                                ) {
                                    Text("删除任务", color = Color.Red, fontSize = 12.sp)
                                }
                                Button(
                                    onClick = {
                                        if (task.url.isNotBlank() && task.boundPath.isNotBlank()) {
                                            if (!ensureCustomTargetsReady(listOf(task.boundPath))) return@Button
                                            executeTasks(
                                                urls = listOf(task.url),
                                                scope = coroutineScope,
                                                setDownloading = setDownloading,
                                                setTasks = setTasks,
                                                token = githubToken,
                                                targetPaths = listOf(task.boundPath),
                                                context = context,
                                                rules = emptyList()
                                            )
                                        }
                                    },
                                    enabled = !isDownloading && task.url.isNotBlank() && task.boundPath.isNotBlank(),
                                    shape = RoundedCornerShape(6.dp),
                                    colors = ButtonDefaults.buttonColors(containerColor = MorandiGreen)
                                ) {
                                    Text("独立执行此任务", fontSize = 12.sp, fontWeight = FontWeight.Bold)
                                }
                            }
                        }
                    }
                }
            }
        }

        OutlinedButton(
            onClick = {
                val newTask = CustomTask(UUID.randomUUID().toString(), "", "", "DEFAULT")
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
    githubProbeUrls: Map<String, String> = emptyMap()
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
            TaskState("$title ($fileName)", url, githubProbeUrls[url])
        }

        setTasks(activeTasks)
        for (task in activeTasks) {
            downloadAndDeployTask(
                task = task,
                token = token,
                targetPaths = targetPaths,
                context = context,
                rules = rules
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
    rules: List<String>
) {
    withContext(Dispatchers.IO) {
        val stagingDir = File(context.cacheDir, "wanxiang_staging/${UUID.randomUUID()}")
        val tmpFile = File(stagingDir, "${sanitizedFileName(task.url)}.tmp")
        var success = false
        var lastErrorMsg = ""
        var downloadedFrom = ""

        task.appendDebug("任务开始")
        task.appendDebug("源地址：${task.url}")
        task.appendDebug("目标路径：${targetPaths.joinToString { deployPathDisplayName(it) }}")
        task.appendDebug("缓存目录：${stagingDir.absolutePath}")
        task.appendDebug("下载前执行轻量目标探测")
        publishTaskDebug(task)

        var usableTargetPaths = emptyList<String>()

        try {
            val usableTargets = mutableListOf<String>()
            val skippedTargets = mutableListOf<String>()

            targetPaths
                .map { it.trim() }
                .filter { it.isNotBlank() }
                .distinct()
                .forEach { path ->
                    val pathName = deployPathDisplayName(path)

                    if (path == "DEFAULT") {
                        if (canWriteDefaultRime()) {
                            usableTargets.add(path)
                            task.appendDebug("目标可用：$pathName（所有文件访问权限已授予）")
                        } else {
                            skippedTargets.add("$pathName：缺少所有文件访问权限")
                            task.appendDebug("跳过目标：$pathName（缺少所有文件访问权限）")
                        }
                        return@forEach
                    }

                    if (isRootTarget(path)) {
                        if (RootShell.isAvailable()) {
                            usableTargets.add(path)
                            task.appendDebug("目标可用：$pathName（root 权限已就绪）")
                        } else {
                            skippedTargets.add("$pathName：设备无 root 权限")
                            task.appendDebug("跳过目标：$pathName（设备无 root 权限）")
                        }
                        return@forEach
                    }

                    val uri = runCatching { Uri.parse(path) }.getOrNull()
                    if (uri == null) {
                        skippedTargets.add("$pathName：SAF地址无效")
                        task.appendDebug("跳过目标：$pathName（SAF地址无效）")
                        return@forEach
                    }

                    val probeError = probeSafTreeWriteAccess(context, uri)
                    if (probeError == null) {
                        usableTargets.add(path)
                        task.appendDebug("目标可用：$pathName（SAF小文件探测通过）")
                    } else {
                        skippedTargets.add("$pathName：$probeError")
                        task.appendDebug("跳过目标：$pathName（$probeError）")
                    }
                }

            usableTargetPaths = usableTargets

            if (skippedTargets.isNotEmpty()) {
                task.appendDebug("本次跳过目标：${skippedTargets.joinToString()}")
            }
            publishTaskDebug(task)

            if (usableTargetPaths.isEmpty()) {
                withContext(Dispatchers.Main) {
                    task.isError = true
                    task.progress = 0f
                    task.status = "❌ 没有可写目标"
                }
                return@withContext
            }

            if (!stagingDir.mkdirs() && !stagingDir.isDirectory) {
                throw Exception("无法创建临时目录")
            }

            withContext(Dispatchers.Main) {
                task.isFinished = false
                task.isError = false
                task.progress = 0f
                task.status = "准备中..."
            }

            val isLocalFile = task.url.startsWith("/") ||
                task.url.startsWith("file://") ||
                task.url.startsWith("content://")

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
                    task.appendDebug("本地文件读取完成：${tmpFile.length()} 字节")
                    success = true
                    downloadedFrom = "本地文件"

                    withContext(Dispatchers.Main) {
                        task.progress = 1f
                        task.status = "本地读取完成"
                    }
                } catch (error: Exception) {
                    lastErrorMsg = error.message ?: "本地文件读取异常"
                    task.appendDebug("本地文件读取失败：${error.javaClass.simpleName}: $lastErrorMsg", error)
                    publishTaskDebug(task)
                }
            } else {
                // CNB 模式下先向对应 GitHub Release 发一次 4 字节 GET。
                // 该操作完全静默，失败不会记录、不会重试、不会影响 CNB 下载。
                task.githubProbeUrl?.let { silentGithubShortDownloadRequest(it, token) }

                val expectedZip = task.url.substringBefore("?").endsWith(".zip", true)
                val sourceName = when {
                    task.url.contains("cnb.cool", true) -> "CNB"
                    task.url.contains("github.com", true) -> "GitHub"
                    else -> runCatching { URL(task.url).host }.getOrDefault("直链")
                }

                // 恢复旧版下载过程：手动追踪重定向 -> HEAD 取长度 -> 三线程分段；
                // 无法获得长度时自动改用单线程。最多重试 3 次，不再经过任何代理。
                for (attempt in 1..3) {
                    var finalUrlStr = task.url
                    try {
                        tmpFile.delete()
                        withContext(Dispatchers.Main) {
                            task.progress = 0f
                            task.status = if (attempt > 1) {
                                "$sourceName 重试中($attempt/3)"
                            } else {
                                "连接 $sourceName..."
                            }
                        }
                        task.appendDebug("开始下载：$sourceName，第 $attempt 次，url=${task.url}")

                        var redirectCount = 0
                        while (redirectCount < 5) {
                            var redirectConn: HttpURLConnection? = null
                            try {
                                val redirectUrl = URL(finalUrlStr)
                                redirectConn = redirectUrl.openConnection() as HttpURLConnection
                                redirectConn.instanceFollowRedirects = false
                                redirectConn.requestMethod = "HEAD"
                                redirectConn.connectTimeout = 10000
                                redirectConn.readTimeout = 10000
                                redirectConn.setRequestProperty(
                                    "User-Agent",
                                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                                )
                                if (redirectUrl.host.equals("github.com", true) && token.isNotBlank()) {
                                    redirectConn.setRequestProperty("Authorization", "Bearer ${token.trim()}")
                                }

                                val code = redirectConn.responseCode
                                task.appendDebug("重定向探测：code=$code，url=$finalUrlStr")
                                if (code in listOf(301, 302, 303, 307, 308)) {
                                    val location = redirectConn.getHeaderField("Location")
                                    if (!location.isNullOrBlank()) {
                                        finalUrlStr = if (location.startsWith("http")) {
                                            location
                                        } else {
                                            URL(redirectUrl, location).toString()
                                        }
                                        redirectCount++
                                        continue
                                    }
                                }
                                break
                            } finally {
                                redirectConn?.disconnect()
                            }
                        }

                        val finalUrl = URL(finalUrlStr)
                        var totalSize = 0L
                        var rangeSupported = false
                        var sizeConn: HttpURLConnection? = null

                        try {
                            sizeConn = finalUrl.openConnection() as HttpURLConnection
                            sizeConn.requestMethod = "HEAD"
                            sizeConn.connectTimeout = 10000
                            sizeConn.readTimeout = 10000
                            sizeConn.setRequestProperty(
                                "User-Agent",
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                            )
                            sizeConn.setRequestProperty("Accept-Encoding", "identity")
                            if (finalUrl.host.equals("github.com", true) && token.isNotBlank()) {
                                sizeConn.setRequestProperty("Authorization", "Bearer ${token.trim()}")
                            }

                            val code = sizeConn.responseCode
                            if (code == 200 || code == 206) {
                                totalSize = sizeConn.getHeaderFieldLong("Content-Length", -1L).coerceAtLeast(0L)
                                rangeSupported = sizeConn.getHeaderField("Accept-Ranges")
                                    ?.contains("bytes", true) == true
                            }
                            task.appendDebug(
                                "文件信息：code=$code，size=$totalSize，acceptRanges=$rangeSupported，final=$finalUrlStr"
                            )
                        } finally {
                            sizeConn?.disconnect()
                        }

                        if (totalSize > 0L && rangeSupported) {
                            val threadCount = 3
                            val chunkSize = totalSize / threadCount
                            val downloadedLen = AtomicLong(0L)
                            val lastUpdateTime = AtomicLong(System.currentTimeMillis())
                            val partFiles = (0 until threadCount).map { index ->
                                File(stagingDir, "${tmpFile.name}.part$index")
                            }

                            try {
                                coroutineScope {
                                    (0 until threadCount).map { index ->
                                        async(Dispatchers.IO) {
                                            val start = index * chunkSize
                                            val end = if (index == threadCount - 1) {
                                                totalSize - 1
                                            } else {
                                                start + chunkSize - 1
                                            }

                                            var partConn: HttpURLConnection? = null
                                            try {
                                                partConn = URL(finalUrlStr).openConnection() as HttpURLConnection
                                                partConn.connectTimeout = 10000
                                                partConn.readTimeout = 15000
                                                partConn.setRequestProperty(
                                                    "User-Agent",
                                                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                                                )
                                                partConn.setRequestProperty("Range", "bytes=$start-$end")
                                                partConn.setRequestProperty("Accept-Encoding", "identity")
                                                if (URL(finalUrlStr).host.equals("github.com", true) && token.isNotBlank()) {
                                                    partConn.setRequestProperty("Authorization", "Bearer ${token.trim()}")
                                                }

                                                val responseCode = partConn.responseCode
                                                if (responseCode != 206) {
                                                    throw Exception("服务器未接受分段请求：HTTP $responseCode")
                                                }

                                                val partFile = partFiles[index]
                                                partConn.inputStream.buffered().use { input ->
                                                    FileOutputStream(partFile).buffered().use { output ->
                                                        val data = ByteArray(64 * 1024)
                                                        while (true) {
                                                            val count = input.read(data)
                                                            if (count < 0) break
                                                            output.write(data, 0, count)

                                                            val currentDownloaded = downloadedLen.addAndGet(count.toLong())
                                                            val currentTime = System.currentTimeMillis()
                                                            val previous = lastUpdateTime.get()
                                                            if (currentTime - previous > 150L &&
                                                                lastUpdateTime.compareAndSet(previous, currentTime)
                                                            ) {
                                                                val speedText = formatDownloadSpeed(
                                                                    currentDownloaded * 1000L /
                                                                        (currentTime - previous + 1L).coerceAtLeast(1L)
                                                                )
                                                                withContext(Dispatchers.Main) {
                                                                    task.progress = (currentDownloaded.toDouble() / totalSize.toDouble())
                                                                        .toFloat()
                                                                        .coerceIn(0f, 1f)
                                                                    task.status = "$sourceName ${String.format("%.1f", currentDownloaded / 1024.0 / 1024.0)}MB / " +
                                                                        "${String.format("%.1f", totalSize / 1024.0 / 1024.0)}MB · 多线程"
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            } finally {
                                                partConn?.disconnect()
                                            }
                                        }
                                    }.awaitAll()
                                }

                                val expectedPartSizes = (0 until threadCount).map { index ->
                                    val start = index * chunkSize
                                    val end = if (index == threadCount - 1) totalSize - 1 else start + chunkSize - 1
                                    end - start + 1
                                }
                                partFiles.forEachIndexed { index, partFile ->
                                    if (!partFile.exists() || partFile.length() != expectedPartSizes[index]) {
                                        throw Exception(
                                            "分段文件不完整：part$index ${partFile.length()}/${expectedPartSizes[index]}"
                                        )
                                    }
                                }

                                withContext(Dispatchers.Main) { task.status = "文件拼装中..." }
                                FileOutputStream(tmpFile).buffered().use { output ->
                                    partFiles.forEach { partFile ->
                                        partFile.inputStream().buffered().use { input -> input.copyTo(output) }
                                    }
                                }
                            } finally {
                                partFiles.forEach { it.delete() }
                            }
                        } else {
                            var conn: HttpURLConnection? = null
                            try {
                                conn = URL(finalUrlStr).openConnection() as HttpURLConnection
                                conn.instanceFollowRedirects = true
                                conn.connectTimeout = 10000
                                conn.readTimeout = 60000
                                conn.setRequestProperty(
                                    "User-Agent",
                                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                                )
                                conn.setRequestProperty("Accept-Encoding", "identity")
                                if (URL(finalUrlStr).host.equals("github.com", true) && token.isNotBlank()) {
                                    conn.setRequestProperty("Authorization", "Bearer ${token.trim()}")
                                }

                                val responseCode = conn.responseCode
                                if (responseCode !in 200..299) throw Exception("HTTP $responseCode")
                                val fallbackSize = conn.getHeaderFieldLong("Content-Length", -1L)
                                withContext(Dispatchers.Main) {
                                    task.progress = if (fallbackSize > 0L) 0f else -1f
                                }

                                var downloaded = 0L
                                val transferStartedAt = System.currentTimeMillis()
                                var lastUiUpdate = 0L
                                conn.inputStream.buffered().use { input ->
                                    FileOutputStream(tmpFile).buffered().use { output ->
                                        val data = ByteArray(128 * 1024)
                                        while (true) {
                                            val count = input.read(data)
                                            if (count < 0) break
                                            output.write(data, 0, count)
                                            downloaded += count

                                            val now = System.currentTimeMillis()
                                            if (now - lastUiUpdate >= 150L) {
                                                lastUiUpdate = now
                                                val elapsed = (now - transferStartedAt).coerceAtLeast(1L)
                                                val speed = formatDownloadSpeed(downloaded * 1000L / elapsed)
                                                withContext(Dispatchers.Main) {
                                                    if (fallbackSize > 0L) {
                                                        task.progress = (downloaded.toDouble() / fallbackSize.toDouble())
                                                            .toFloat()
                                                            .coerceIn(0f, 1f)
                                                        task.status = "$sourceName ${String.format("%.1f", downloaded / 1024.0 / 1024.0)}MB / " +
                                                            "${String.format("%.1f", fallbackSize / 1024.0 / 1024.0)}MB · $speed"
                                                    } else {
                                                        task.progress = -1f
                                                        task.status = "$sourceName ${String.format("%.1f", downloaded / 1024.0 / 1024.0)}MB · $speed"
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }

                                if (fallbackSize > 0L && tmpFile.length() != fallbackSize) {
                                    throw Exception("文件不完整：${tmpFile.length()}/$fallbackSize")
                                }
                            } finally {
                                conn?.disconnect()
                            }
                        }

                        if (!tmpFile.exists() || tmpFile.length() == 0L) throw Exception("下载文件为空")
                        if (looksLikeErrorPayload(tmpFile)) {
                            throw Exception("服务器返回了错误内容（${tmpFile.length()}B）")
                        }
                        if (expectedZip && !isUsableZip(tmpFile)) {
                            throw Exception("返回内容不是有效ZIP（${tmpFile.length()}B）")
                        }

                        success = true
                        downloadedFrom = sourceName
                        task.appendDebug("下载校验通过：来源=$sourceName，大小=${tmpFile.length()} 字节")
                        publishTaskDebug(task)

                        withContext(Dispatchers.Main) {
                            task.progress = 1f
                            task.status = "下载完成（$sourceName）"
                        }
                        break
                    } catch (error: Exception) {
                        lastErrorMsg = "$sourceName: ${error.message ?: "网络异常"}"
                        task.appendDebug(
                            "下载失败：$lastErrorMsg (${error.javaClass.simpleName})",
                            error
                        )
                        tmpFile.delete()

                        withContext(Dispatchers.Main) {
                            task.progress = 0f
                            task.status = "⚠️ $lastErrorMsg"
                        }
                        if (attempt < 3) delay(1000)
                    }
                }
            }

            if (!success) {
                task.appendDebug("下载失败：$lastErrorMsg")
                publishTaskDebug(task)
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
            task.appendDebug(
                "文件识别：name=${sanitizedFileName(task.url)}, size=${tmpFile.length()}, isZip=$isZipArchive"
            )

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
                                if (!parent.mkdirs() && !parent.isDirectory) {
                                    throw Exception("无法创建目录：${parent.name}")
                                }
                            }
                            FileOutputStream(outputFile).buffered().use { output -> zis.copyTo(output) }
                        }
                        zis.closeEntry()
                        entry = zis.nextEntry
                    }
                }
            } else {
                val stagedFile = File(extractDir, sanitizedFileName(task.url))
                if (stagedFile.exists() && !stagedFile.delete()) {
                    throw Exception("无法清理缓存中的旧临时文件：${stagedFile.name}")
                }

                if (!tmpFile.renameTo(stagedFile)) {
                    tmpFile.inputStream().buffered().use { input ->
                        FileOutputStream(stagedFile, false).buffered().use { output -> input.copyTo(output) }
                    }
                    if (!tmpFile.delete()) tmpFile.deleteOnExit()
                }
            }

            var realSrcDir = extractDir
            val subFiles = extractDir.listFiles()
            if (subFiles != null && subFiles.size == 1 && subFiles[0].isDirectory) {
                realSrcDir = subFiles[0]
            }

            task.appendDebug(
                "暂存完成：realSrc=${realSrcDir.absolutePath}，顶层=" +
                    realSrcDir.listFiles().orEmpty().take(20).joinToString {
                        "${it.name}${if (it.isDirectory) "/" else "(${it.length()}B)"}"
                    }
            )
            publishTaskDebug(task)

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
            val orderedTargetPaths = usableTargetPaths.sortedBy { if (it == "DEFAULT") 1 else 0 }

            task.appendDebug("实际部署顺序：${orderedTargetPaths.joinToString { deployPathDisplayName(it) }}")
            publishTaskDebug(task)

            val fileDebug: (String) -> Unit = { message -> task.appendDebug(message) }

            for ((index, pathStr) in orderedTargetPaths.withIndex()) {
                val pathName = deployPathDisplayName(pathStr)

                try {
                    task.appendDebug("开始目标：$pathName，raw=$pathStr")
                    if (index > 0) delay(300)

                    withContext(Dispatchers.Main) {
                        task.status = "部署 $pathName ${index + 1}/${orderedTargetPaths.size}（$downloadedFrom）..."
                    }

                    if (pathStr == "DEFAULT") {
                        if (!canWriteDefaultRime()) throw Exception("缺少所有文件访问权限，已跳过")

                        val root = File(Environment.getExternalStorageDirectory(), "rime")
                        val target = if (isDict) File(root, "dicts") else root
                        task.appendDebug(
                            "普通目录：root=${root.absolutePath}, target=${target.absolutePath}, " +
                                "exists=${target.exists()}, canWrite=${target.canWrite()}"
                        )
                        copyNormal(realSrcDir, target, excludeRegexList, debug = fileDebug)
                    } else if (isRootTarget(pathStr)) {
                        if (!RootShell.isAvailable()) throw Exception("设备无 root 权限，已跳过")

                        val targetRoot = File(rootTargetPath(pathStr))
                        val target = if (isDict) File(targetRoot, "dicts") else targetRoot
                        task.appendDebug(
                            "Root目录：target=${target.absolutePath}, " +
                                "exists=${RootShell.exists(target.absolutePath)}"
                        )
                        copyRoot(realSrcDir, target, excludeRegexList, debug = fileDebug)
                    } else {
                        val targetUri = Uri.parse(pathStr)
                        val rootDoc = DocumentFile.fromTreeUri(context, targetUri)
                            ?: throw Exception("无法解析SAF授权目录")

                        var targetDoc = rootDoc
                        if (isDict) {
                            targetDoc = rootDoc.findFile("dicts")
                                ?: rootDoc.createDirectory("dicts")
                                ?: rootDoc.findFile("dicts")
                                ?: throw Exception("SAF底层拒绝创建dicts目录")
                        }

                        task.appendDebug(
                            "SAF目录：name=${targetDoc.name}, uri=${targetDoc.uri}, " +
                                "exists=${targetDoc.exists()}, canWrite=${targetDoc.canWrite()}"
                        )
                        copySaf(context, realSrcDir, targetDoc, excludeRegexList, debug = fileDebug)
                    }

                    successCount++
                    task.appendDebug("目标成功：$pathName")
                    publishTaskDebug(task)
                } catch (error: Exception) {
                    val detail = "$pathName(${error.javaClass.simpleName}: ${error.message ?: "无错误信息"})"
                    errorList.add(detail)
                    task.appendDebug("目标失败：$detail", error)
                    publishTaskDebug(task)
                }
            }

            task.appendDebug(
                "部署汇总：success=$successCount/${orderedTargetPaths.size}, errors=${errorList.joinToString()}"
            )
            publishTaskDebug(task)

            withContext(Dispatchers.Main) {
                val successText = if (isZipArchive) "解压并部署完成" else "文件部署完成"
                when {
                    successCount == orderedTargetPaths.size && orderedTargetPaths.isNotEmpty() -> {
                        task.isFinished = true
                        task.progress = 1f
                        task.status = "✅ $successText（$downloadedFrom）"
                    }
                    successCount > 0 -> {
                        task.isFinished = true
                        task.progress = 1f
                        task.status = "⚠️ 部分完成 [失败: ${errorList.joinToString()}]"
                    }
                    else -> {
                        task.isError = true
                        task.progress = 0f
                        task.status = "❌ 全部部署失败 [${errorList.joinToString()}]"
                    }
                }
            }
        } catch (error: Exception) {
            task.appendDebug(
                "任务级异常：${error.javaClass.name}: ${error.message ?: "无错误信息"}",
                error
            )
            publishTaskDebug(task)
            withContext(Dispatchers.Main) {
                task.isError = true
                task.progress = 0f
                task.status = "❌ 文件处理失败：${error.message ?: error.javaClass.simpleName}"
            }
        } finally {
            val deleted = stagingDir.deleteRecursively()
            task.appendDebug("清理缓存：$deleted，path=${stagingDir.absolutePath}")
            publishTaskDebug(task)
        }
    }
}

fun isProtectedExistingFile(
    relPath: String,
    exists: Boolean,
    rules: List<Regex>
): Boolean {
    return exists && rules.any { it.containsMatchIn(relPath) }
}

fun replaceNormalFileByDeleteThenMove(
    src: File,
    target: File,
    relPath: String,
    debug: (String) -> Unit = {}
) {
    val parent = target.parentFile ?: throw Exception("目标文件没有父目录：$relPath")

    if (!parent.exists() && !parent.mkdirs()) {
        throw Exception("无法创建目标目录：${parent.absolutePath}")
    }

    val tempTarget = File(parent, ".${target.name}.wanxiang-${UUID.randomUUID()}.tmp")

    debug(
        "[NORMAL] 准备文件：$relPath，src=${src.length()}B，" +
            "targetExists=${target.exists()}，temp=${tempTarget.name}"
    )

    try {
        src.inputStream().buffered().use { input ->
            FileOutputStream(tempTarget, false).buffered().use { output -> input.copyTo(output) }
        }

        debug("[NORMAL] 临时文件写入完成：$relPath，size=${tempTarget.length()}B")

        if (!tempTarget.exists() || tempTarget.length() != src.length()) {
            throw Exception("目标侧临时文件校验失败：$relPath")
        }

        if (target.exists()) {
            val deleted = target.delete()
            debug("[NORMAL] 删除旧文件：$relPath，result=$deleted")
            if (!deleted) throw Exception("无法删除旧文件，可能正被占用或无权限：$relPath")
        }

        val moved = tempTarget.renameTo(target)
        debug("[NORMAL] 移动临时文件：$relPath，result=$moved")
        if (!moved) throw Exception("旧文件已删除，但临时文件移动失败：$relPath")
    } finally {
        if (tempTarget.exists()) {
            val cleaned = tempTarget.delete()
            debug("[NORMAL] 清理残留临时文件：$relPath，result=$cleaned")
        }
    }
}

fun copyNormal(
    src: File,
    dest: File,
    rules: List<Regex>,
    currentPath: String = "",
    debug: (String) -> Unit = {}
) {
    if (!dest.exists() && !dest.mkdirs()) throw Exception("无法创建目标目录：${dest.absolutePath}")
    if (!dest.isDirectory) throw Exception("目标路径不是目录：${dest.absolutePath}")

    val children = src.listFiles() ?: throw Exception("无法读取暂存目录：${src.absolutePath}")

    children.forEach { file ->
        val relPath = if (currentPath.isEmpty()) file.name else "$currentPath/${file.name}"
        val targetFile = File(dest, file.name)
        val protected = isProtectedExistingFile(relPath, targetFile.exists(), rules)

        debug(
            "[NORMAL] 检查：$relPath，dir=${file.isDirectory}，" +
                "targetExists=${targetFile.exists()}，protected=$protected"
        )

        if (protected) {
            debug("[NORMAL] 白名单跳过：$relPath")
            return@forEach
        }

        if (file.isDirectory) {
            if (targetFile.exists() && !targetFile.isDirectory) {
                val deleted = targetFile.delete()
                debug("[NORMAL] 删除同名文件以创建目录：$relPath，result=$deleted")
                if (!deleted) throw Exception("同名文件阻止创建目录：$relPath")
            }
            copyNormal(file, targetFile, rules, relPath, debug)
        } else {
            if (targetFile.exists() && targetFile.isDirectory) {
                throw Exception("同名目录阻止替换文件：$relPath")
            }
            replaceNormalFileByDeleteThenMove(file, targetFile, relPath, debug)
        }
    }
}

/**
 * 以 root 权限递归部署：语义与 [copyNormal] 对齐（白名单跳过、同名冲突处理），
 * 但所有文件系统操作都通过 su 执行，可写入 SAF 到不了的系统目录。
 */
fun copyRoot(
    src: File,
    dest: File,
    rules: List<Regex>,
    currentPath: String = "",
    owner: String? = null,
    selinuxContext: String? = null,
    debug: (String) -> Unit = {}
) {
    val destPath = dest.absolutePath

    if (!RootShell.mkdirs(destPath)) throw Exception("root 无法创建目标目录：$destPath")
    if (!RootShell.isDirectory(destPath)) throw Exception("root 目标路径不是目录：$destPath")

    // 继承目标根目录的属主/属组与 SELinux 上下文：保证 chmod 660/770 对目标 App 生效，
    // 否则 group 位不匹配时 660 反而会让 App 完全无法访问；SELinux 上下文不对时
    // enforcing 模式下 App 同样被拒。只有最外层读取真实值，递归层沿用外层传入的，
    // 因为递归创建的子目录/文件属主是 root（mkdir/cat 默认），重新读取会拿错。
    val rootOwner = owner ?: RootShell.ownerOf(destPath)
    val rootContext = selinuxContext ?: RootShell.selinuxContextOf(destPath)
    if (rootOwner == null) {
        debug("[ROOT] 无法读取目标目录属主：$destPath，将保持默认权限")
    } else if (owner == null) {
        debug("[ROOT] 目标属主：$destPath → $rootOwner")
    }
    if (rootContext == null) {
        debug("[ROOT] 无法读取目标目录 SELinux 上下文：$destPath（SELinux 可能未启用）")
    } else if (selinuxContext == null) {
        debug("[ROOT] 目标 SELinux 上下文：$destPath → $rootContext")
    }

    val children = src.listFiles() ?: throw Exception("无法读取暂存目录：${src.absolutePath}")

    children.forEach { file ->
        val relPath = if (currentPath.isEmpty()) file.name else "$currentPath/${file.name}"
        val targetPath = File(dest, file.name).absolutePath
        val targetExists = RootShell.exists(targetPath)
        val protected = isProtectedExistingFile(relPath, targetExists, rules)

        debug(
            "[ROOT] 检查：$relPath，dir=${file.isDirectory}，" +
                "targetExists=$targetExists，protected=$protected"
        )

        if (protected) {
            debug("[ROOT] 白名单跳过：$relPath")
            return@forEach
        }

        if (file.isDirectory) {
            if (targetExists && !RootShell.isDirectory(targetPath)) {
                val deleted = RootShell.delete(targetPath)
                debug("[ROOT] 删除同名文件以创建目录：$relPath，result=$deleted")
                if (!deleted) throw Exception("root 删除同名文件失败：$relPath")
            }
            copyRoot(file, File(targetPath), rules, relPath, rootOwner, rootContext, debug)
            applyRootOwner(
                path = targetPath,
                isDir = true,
                owner = rootOwner,
                selinuxContext = rootContext,
                relPath = relPath,
                debug = debug
            )
        } else {
            if (targetExists && RootShell.isDirectory(targetPath)) {
                throw Exception("root 同名目录阻止替换文件：$relPath")
            }
            replaceRootFileByDeleteThenCopy(
                src = file,
                target = File(targetPath),
                relPath = relPath,
                owner = rootOwner,
                selinuxContext = rootContext,
                debug = debug
            )
        }
    }
}

/** 递归部署结束后，把目录/文件的属主、SELinux 上下文与权限修正为目标 owner（660 文件 / 770 目录）。 */
fun applyRootOwner(
    path: String,
    isDir: Boolean,
    owner: String?,
    selinuxContext: String?,
    relPath: String,
    debug: (String) -> Unit = {}
) {
    val mode = if (isDir) "770" else "660"
    if (owner != null) {
        val owned = RootShell.chown(path, owner)
        debug("[ROOT] 设置属主：$relPath → $owner，result=$owned")
        if (!owned) debug("[ROOT] 属主设置失败（不影响部署，目标 App 可能无法写）：$relPath")
    }
    if (selinuxContext != null) {
        val recon = RootShell.chcon(path, selinuxContext)
        debug("[ROOT] 设置 SELinux 上下文：$relPath → $selinuxContext，result=$recon")
        if (!recon) debug("[ROOT] SELinux 上下文设置失败（enforcing 模式下目标 App 可能被拒）：$relPath")
    }
    val chmodded = RootShell.chmod(path, mode)
    debug("[ROOT] 设置权限：$relPath → $mode，result=$chmodded")
    if (!chmodded) debug("[ROOT] 权限设置失败（目标 App 可能无法访问）：$relPath")
}

/** 用 root 权限原子替换文件：先写临时文件，再删旧文件，最后移动（避免半截文件）。 */
fun replaceRootFileByDeleteThenCopy(
    src: File,
    target: File,
    relPath: String,
    owner: String? = null,
    selinuxContext: String? = null,
    debug: (String) -> Unit = {}
) {
    val parentPath = target.parent ?: throw Exception("目标文件没有父目录：$relPath")
    if (!RootShell.mkdirs(parentPath)) throw Exception("root 无法创建目标目录：$parentPath")

    val tempName = ".${target.name}.wanxiang-${UUID.randomUUID()}.tmp"
    val tempPath = File(parentPath, tempName).absolutePath

    debug(
        "[ROOT] 准备文件：$relPath，src=${src.length()}B，" +
            "targetExists=${RootShell.exists(target.absolutePath)}，temp=$tempName"
    )

    try {
        if (!RootShell.copyFile(src, File(tempPath))) {
            throw Exception("root 写入临时文件失败：$relPath")
        }
        debug("[ROOT] 临时文件写入完成：$relPath，size=${RootShell.fileSize(tempPath)}")

        if (RootShell.exists(target.absolutePath)) {
            val deleted = RootShell.delete(target.absolutePath)
            debug("[ROOT] 删除旧文件：$relPath，result=$deleted")
            if (!deleted) throw Exception("root 无法删除旧文件：$relPath")
        }

        val moved = RootShell.move(tempPath, target.absolutePath)
        debug("[ROOT] 移动临时文件：$relPath，result=$moved")
        if (!moved) throw Exception("旧文件已删除，但 root 移动临时文件失败：$relPath")

        applyRootOwner(
            path = target.absolutePath,
            isDir = false,
            owner = owner,
            selinuxContext = selinuxContext,
            relPath = relPath,
            debug = debug
        )
    } finally {
        if (RootShell.exists(tempPath)) {
            val cleaned = RootShell.delete(tempPath)
            debug("[ROOT] 清理残留临时文件：$relPath，result=$cleaned")
        }
    }
}

fun writeSourceToSafDocument(
    context: Context,
    src: File,
    document: DocumentFile,
    relPath: String,
    debug: (String) -> Unit = {}
) {
    debug(
        "[SAF] 打开写入流：$relPath，uri=${document.uri}，" +
            "src=${src.length()}B，docExists=${document.exists()}"
    )

    var written = 0L
    context.contentResolver.openOutputStream(document.uri, "w")?.use { output ->
        src.inputStream().buffered().use { input ->
            val buffer = ByteArray(128 * 1024)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                output.write(buffer, 0, count)
                written += count
            }
            output.flush()
        }
    } ?: throw Exception("SAF无法打开写入流：$relPath")

    debug("[SAF] 写入完成：$relPath，written=${written}B")
    if (written != src.length()) {
        throw Exception("SAF写入大小不一致：$relPath，$written/${src.length()}")
    }
}

fun replaceSafFileByDeleteThenCreate(
    context: Context,
    src: File,
    dest: DocumentFile,
    existingFile: DocumentFile?,
    relPath: String,
    debug: (String) -> Unit = {}
) {
    debug(
        "[SAF] 准备替换：$relPath，existing=${existingFile?.exists() == true}，" +
            "dest=${dest.uri}"
    )

    if (existingFile != null && existingFile.exists()) {
        val deleted = existingFile.delete()
        debug("[SAF] 删除旧文件：$relPath，result=$deleted，uri=${existingFile.uri}")
        if (!deleted) throw Exception("SAF无法删除旧文件，可能正被占用或授权不足：$relPath")
    }

    val newDoc = dest.createFile("*/*", src.name)
        ?: throw Exception("SAF删除旧文件后无法创建新文件：$relPath")

    debug("[SAF] 创建最终文件：$relPath，name=${newDoc.name}，uri=${newDoc.uri}")

    try {
        writeSourceToSafDocument(context, src, newDoc, relPath, debug)
    } catch (error: Exception) {
        val cleaned = runCatching { newDoc.delete() }.getOrDefault(false)
        debug("[SAF] 写入失败后清理新文件：$relPath，result=$cleaned")
        throw error
    }
}

fun copySaf(
    context: Context,
    src: File,
    dest: DocumentFile,
    rules: List<Regex>,
    currentPath: String = "",
    debug: (String) -> Unit = {}
) {
    val children = src.listFiles() ?: throw Exception("无法读取暂存目录：${src.absolutePath}")

    children.forEach { file ->
        val relPath = if (currentPath.isEmpty()) file.name else "$currentPath/${file.name}"
        val existing = dest.findFile(file.name)
        val protected = isProtectedExistingFile(relPath, existing?.exists() == true, rules)

        debug(
            "[SAF] 检查：$relPath，dir=${file.isDirectory}，" +
                "existing=${existing?.exists() == true}，" +
                "existingIsDir=${existing?.isDirectory == true}，protected=$protected"
        )

        if (protected) {
            debug("[SAF] 白名单跳过：$relPath")
            return@forEach
        }

        if (file.isDirectory) {
            var nextDest = existing

            if (nextDest != null && !nextDest.isDirectory) {
                val deleted = nextDest.delete()
                debug("[SAF] 删除同名文件以创建目录：$relPath，result=$deleted")
                if (!deleted) throw Exception("SAF同名文件阻止创建目录：$relPath")
                nextDest = null
            }

            if (nextDest == null) {
                nextDest = dest.createDirectory(file.name) ?: dest.findFile(file.name)
                debug(
                    "[SAF] 创建目录：$relPath，result=${nextDest != null}，" +
                        "uri=${nextDest?.uri}"
                )
            }

            if (nextDest == null || !nextDest.isDirectory) {
                throw Exception("SAF无法创建目录：$relPath")
            }

            copySaf(context, file, nextDest, rules, relPath, debug)
        } else {
            if (existing != null && existing.isDirectory) {
                throw Exception("SAF同名目录阻止替换文件：$relPath")
            }

            replaceSafFileByDeleteThenCreate(
                context = context,
                src = file,
                dest = dest,
                existingFile = existing,
                relPath = relPath,
                debug = debug
            )
        }
    }
}