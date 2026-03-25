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
import androidx.documentfile.provider.DocumentFile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
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

class TaskState(val title: String, val url: String) {
    var progress by mutableStateOf(0f)
    var status by mutableStateOf("等待中...")
    var isFinished by mutableStateOf(false)
    var isError by mutableStateOf(false)
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
        try { context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "1.0" } catch (e: Exception) { "1.0" }
    }

    var showPermissionDialog by remember { 
        mutableStateOf(Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && !Environment.isExternalStorageManager()) 
    }

    if (showPermissionDialog) {
        AlertDialog(
            onDismissRequest = { },
            title = { Text("需要存储访问权限", fontWeight = FontWeight.Bold, fontSize = 18.sp, color = MorandiDarkGreen) },
            text = {
                Text(
                    text = "万象更新器需要【所有文件访问权限】。\n\n" +
                           "这是因为我们需要将最新下载的方案和词库文件，直接写入到您手机根目录的 /rime 文件夹，或小企鹅输入法的私有目录中。",
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
                ) { Text("去授权", fontWeight = FontWeight.Bold) }
            },
            dismissButton = {
                TextButton(onClick = { showPermissionDialog = false }) { Text("暂不更新", color = Color.Gray) }
            },
            containerColor = Color.White
        )
    }

    var isPro by remember { mutableStateOf(true) }
    var auxScheme by remember { mutableStateOf("zrm") }
    var downloadSource by remember { mutableStateOf("CNB") }
    var updateChannel by remember { mutableStateOf("Stable") } 
    
    // 🌟 修复：把 GitHub Token 恢复并带上持久化记忆功能
    var githubToken by remember { 
        mutableStateOf(sharedPref.getString("gh_token", "") ?: "") 
    }
    
    var excludeRulesText by remember { mutableStateOf(sharedPref.getString("exclude_rules", DEFAULT_EXCLUDE_RULES) ?: DEFAULT_EXCLUDE_RULES) }
    var showAdvancedRules by remember { mutableStateOf(false) }

    var savedPaths by remember { 
        mutableStateOf(sharedPref.getStringSet("deploy_paths", setOf("DEFAULT"))?.toList() ?: listOf("DEFAULT")) 
    }
    
    val dirPickerLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            context.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
            val newPaths = (savedPaths + uri.toString()).distinct()
            savedPaths = newPaths
            sharedPref.edit().putStringSet("deploy_paths", newPaths.toSet()).apply()
        }
    }

    // 🌟 核心修正：双核雷达逻辑 (增加 Timeout 和 User-Agent 防止 403)
    var latestStableTag by remember { mutableStateOf("v1.0.0") }
    var cloudVersionName by remember { mutableStateOf("") }
    var updaterDownloadUrl by remember { mutableStateOf("") }
    var isCheckingUpdate by remember { mutableStateOf(true) }

    LaunchedEffect(Unit) {
        withContext(Dispatchers.IO) {
            // 1. 探测主方案 Tag
            try {
                val url = URL("https://api.github.com/repos/amzxyz/rime_wanxiang/releases/latest")
                val conn = url.openConnection() as HttpURLConnection
                conn.setRequestProperty("User-Agent", "WanxiangUpdater-Agent")
                
                // 🌟 修复：在云端探测时如果填写了 Token 也带上防限流
                if (githubToken.isNotBlank()) conn.setRequestProperty("Authorization", "Bearer $githubToken")
                
                conn.connectTimeout = 10000
                conn.connect()
                if (conn.responseCode == 200) {
                    val content = conn.inputStream.bufferedReader().readText()
                    Regex("\"tag_name\"\\s*:\\s*\"([^\"]+)\"").find(content)?.groupValues?.get(1)?.let { latestStableTag = it }
                }
            } catch (e: Exception) { e.printStackTrace() }

            // 2. 探测更新器自身 (修复 403 和卡死)
            try {
                val toolUrl = URL("https://api.github.com/repos/amzxyz/RIME-LMDG/releases/tags/tool")
                val toolConn = toolUrl.openConnection() as HttpURLConnection
                toolConn.setRequestProperty("User-Agent", "WanxiangUpdater-Agent") // 必须加，否则易报 403
                
                // 🌟 修复：在云端探测时如果填写了 Token 也带上防限流
                if (githubToken.isNotBlank()) toolConn.setRequestProperty("Authorization", "Bearer $githubToken")
                
                toolConn.connectTimeout = 10000
                toolConn.readTimeout = 10000
                toolConn.connect()
                
                if (toolConn.responseCode == 200) {
                    val content = toolConn.inputStream.bufferedReader().readText()
                    val json = org.json.JSONObject(content)
                    val assets = json.getJSONArray("assets")
                    for (i in 0 until assets.length()) {
                        val asset = assets.getJSONObject(i)
                        val name = asset.getString("name")
                        // 🌟 精准前缀提取：必须 Wanxiang-Updater-Android 开头
                        if (name.startsWith("Wanxiang-Updater-Android") && name.endsWith(".apk")) {
                            updaterDownloadUrl = asset.getString("browser_download_url")
                            val versionMatch = Regex("""Wanxiang-Updater-Android.*?(\d+\.\d+(\.\d+)?)""").find(name)
                            cloudVersionName = versionMatch?.groupValues?.get(1) ?: ""
                            break
                        }
                    }
                }
            } catch (e: Exception) { e.printStackTrace() }
            isCheckingUpdate = false
        }
    }

    var isDownloading by remember { mutableStateOf(false) }
    var activeTasks by remember { mutableStateOf<List<TaskState>>(emptyList()) }
    val coroutineScope = rememberCoroutineScope()

    val auxMap = mapOf("zrm" to "自然码", "flypy" to "小鹤", "moqi" to "墨奇", "hanxin" to "汉心", "shouyou" to "首右", "tiger" to "虎码", "wubi" to "五笔")

    Column(modifier = Modifier.padding(16.dp).verticalScroll(rememberScrollState())) {
        Text("📱 万象拼音更新器", fontSize = 24.sp, fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
        Text("v$localVersionName • 多核分发 & 自我更新", fontSize = 12.sp, color = Color.Gray)
        Spacer(modifier = Modifier.height(16.dp))

        // 🌟 新增 UI：版本对狙卡片
        Card(
            colors = CardDefaults.cardColors(containerColor = Color.White), 
            border = CardDefaults.outlinedCardBorder(true), 
            elevation = CardDefaults.cardElevation(2.dp),
            modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(12.dp).fillMaxWidth()) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("🔧 更新器检测", fontWeight = FontWeight.Bold, color = Color.DarkGray, fontSize = 14.sp)
                    Text(
                        text = if (isCheckingUpdate) "正在检测云端..." 
                               else if (cloudVersionName.isEmpty()) "未发现有效更新包"
                               else if (cloudVersionName > localVersionName) "发现新版本: v$cloudVersionName"
                               else "已是最新版本",
                        fontSize = 12.sp, 
                        color = if (!isCheckingUpdate && cloudVersionName > localVersionName) MorandiGreen else Color.Gray
                    )
                }
                val hasNewVersion = !isCheckingUpdate && cloudVersionName.isNotEmpty() && cloudVersionName > localVersionName
                Button(
                    onClick = { if (updaterDownloadUrl.isNotBlank()) context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(updaterDownloadUrl))) },
                    enabled = hasNewVersion,
                    colors = ButtonDefaults.buttonColors(containerColor = if (hasNewVersion) MorandiGreen else Color.LightGray),
                    modifier = Modifier.height(32.dp),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 0.dp)
                ) {
                    Text(if (hasNewVersion) "立即更新" else "无需操作", fontSize = 12.sp, fontWeight = FontWeight.Bold)
                }
            }
        }

        // 路径展示卡片
        Card(colors = CardDefaults.cardColors(containerColor = MorandiLightGreen), border = CardDefaults.outlinedCardBorder(true), modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text("📁 目标集 (同时分发至以下目录)", fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
                Spacer(modifier = Modifier.height(8.dp))
                if (savedPaths.isEmpty()) Text("⚠️ 未配置路径", fontSize = 12.sp, color = Color.Red)
                savedPaths.forEach { pathStr ->
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                        Text(
                            text = if (pathStr == "DEFAULT") "🎯 默认: 手机根目录 /rime" else "🎯 授权: ${Uri.decode(pathStr).substringAfterLast("%3A")}",
                            fontSize = 13.sp, color = Color.DarkGray, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis
                        )
                        TextButton(onClick = { 
                            val newPaths = savedPaths - pathStr
                            savedPaths = newPaths
                            sharedPref.edit().putStringSet("deploy_paths", newPaths.toSet()).apply()
                        }, contentPadding = PaddingValues(0.dp), modifier = Modifier.height(24.dp)) { Text("移除", fontSize = 12.sp, color = Color.Red) }
                    }
                }
                Divider(color = MorandiBorder, modifier = Modifier.padding(vertical = 8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { dirPickerLauncher.launch(null) }, modifier = Modifier.weight(1f).height(36.dp)) { Text("➕ 添加授权目录", fontSize = 12.sp) }
                    if (!savedPaths.contains("DEFAULT")) TextButton(onClick = { 
                        savedPaths = savedPaths + "DEFAULT"; sharedPref.edit().putStringSet("deploy_paths", savedPaths.toSet()).apply()
                    }) { Text("➕ 恢复默认", fontSize = 12.sp, color = MorandiDarkGreen) }
                }
            }
        }
        Spacer(modifier = Modifier.height(12.dp))

        // 方案与通道选择
        Card(colors = CardDefaults.cardColors(containerColor = Color.White), border = CardDefaults.outlinedCardBorder(true), modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text("🚀 更新通道", fontWeight = FontWeight.Bold, color = Color.DarkGray)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = updateChannel == "Stable", onClick = { updateChannel = "Stable" })
                    Text("正式版 (${latestStableTag})", fontSize = 14.sp)
                    Spacer(modifier = Modifier.width(16.dp))
                    RadioButton(selected = updateChannel == "Preview", onClick = { updateChannel = "Preview" })
                    Text("预览版", fontSize = 14.sp, color = MorandiGreen)
                }
                Divider(color = MorandiLightGreen, modifier = Modifier.padding(vertical = 8.dp))
                Text("📦 方案版本", fontWeight = FontWeight.Bold, color = Color.DarkGray)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = isPro, onClick = { isPro = true }); Text("Pro版", fontSize = 14.sp)
                    Spacer(modifier = Modifier.width(16.dp))
                    RadioButton(selected = !isPro, onClick = { isPro = false }); Text("Base版", fontSize = 14.sp)
                }
                if (isPro) {
                    Divider(color = MorandiLightGreen, modifier = Modifier.padding(vertical = 8.dp))
                    FlowRow(modifier = Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        auxMap.forEach { (key, name) ->
                            FilterChip(selected = (auxScheme == key), onClick = { auxScheme = key }, label = { Text(name, fontSize = 12.sp) })
                        }
                    }
                }
            }
        }
        Spacer(modifier = Modifier.height(12.dp))

        // 高级规则
        Card(colors = CardDefaults.cardColors(containerColor = Color.White), border = CardDefaults.outlinedCardBorder(true), modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.fillMaxWidth()) {
                TextButton(onClick = { showAdvancedRules = !showAdvancedRules }, modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp)) {
                    Text(if (showAdvancedRules) "▼ 收起护盾配置" else "▶ 展开防覆盖保护配置 (高级)", color = MorandiDarkGreen, fontWeight = FontWeight.Bold)
                }
                AnimatedVisibility(visible = showAdvancedRules) {
                    Column(modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 16.dp)) {
                        Text("相对路径命中正则且本地已有该文件，强制跳过覆盖：", fontSize = 11.sp, color = Color.Gray, modifier = Modifier.padding(bottom = 8.dp))
                        OutlinedTextField(
                            value = excludeRulesText,
                            onValueChange = { excludeRulesText = it; sharedPref.edit().putString("exclude_rules", it).apply() },
                            modifier = Modifier.fillMaxWidth().height(160.dp),
                            textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp, fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace)
                        )
                        TextButton(onClick = { 
                            excludeRulesText = DEFAULT_EXCLUDE_RULES; sharedPref.edit().putString("exclude_rules", DEFAULT_EXCLUDE_RULES).apply()
                        }, modifier = Modifier.align(Alignment.End)) { Text("恢复默认规则", fontSize = 12.sp, color = Color.Red) }
                    }
                }
            }
        }
        Spacer(modifier = Modifier.height(12.dp))

        // 下载源
        Card(colors = CardDefaults.cardColors(containerColor = Color.White), border = CardDefaults.outlinedCardBorder(true), modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text("🌐 下载源配置", fontWeight = FontWeight.Bold, color = Color.DarkGray)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = downloadSource == "CNB", onClick = { downloadSource = "CNB" }); Text("CNB", fontSize = 14.sp)
                    Spacer(modifier = Modifier.width(8.dp))
                    RadioButton(selected = downloadSource == "GitHub", onClick = { downloadSource = "GitHub" }); Text("GitHub", fontSize = 14.sp)
                }
                
                // 🌟 修复：把 GitHub Token 输入框带回来了
                if (downloadSource == "GitHub") {
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedTextField(
                        value = githubToken,
                        onValueChange = { 
                            githubToken = it
                            sharedPref.edit().putString("gh_token", it).apply() 
                        },
                        label = { Text("GitHub Token (可选，防限流)", fontSize = 12.sp) },
                        visualTransformation = PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        modifier = Modifier.fillMaxWidth().height(56.dp),
                        singleLine = true
                    )
                }
            }
        }
        Spacer(modifier = Modifier.height(16.dp))

        // 核心下载逻辑
        val schemeStr = if (isPro) auxScheme else "base"
        val activeTag = if (downloadSource == "CNB") (if (updateChannel == "Stable") latestStableTag else "v1.0.0") else (if (updateChannel == "Stable") latestStableTag else "dict-nightly")
        val baseDownloadUrl = if (downloadSource == "CNB") "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/$activeTag" else "https://github.com/amzxyz/rime_wanxiang/releases/download/$activeTag"
        val dictTag = if (downloadSource == "CNB") "v1.0.0" else "dict-nightly"
        val dictBaseUrl = if (downloadSource == "CNB") "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/$dictTag" else "https://github.com/amzxyz/rime_wanxiang/releases/download/$dictTag"
        val schemaUrl = "$baseDownloadUrl/rime-wanxiang-$schemeStr${if(isPro) "-fuzhu" else ""}.zip"
        val dictUrl = "$dictBaseUrl/${if(isPro) "pro-$schemeStr-fuzhu" else "base"}-dicts.zip"
        val modelUrl = if (downloadSource == "CNB") "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/model/wanxiang-lts-zh-hans.gram" else "https://github.com/amzxyz/RIME-LMDG/releases/download/LTS/wanxiang-lts-zh-hans.gram"
        val tasksMap = listOf("🚀 全量更新" to listOf(schemaUrl, dictUrl, modelUrl), "⚙️ 仅方案" to listOf(schemaUrl), "📖 仅词库" to listOf(dictUrl), "🧠 仅模型" to listOf(modelUrl))

        AnimatedVisibility(visible = activeTasks.isNotEmpty()) {
            Card(colors = CardDefaults.cardColors(containerColor = MorandiLightGreen), modifier = Modifier.fillMaxWidth().padding(bottom = 16.dp)) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("📥 任务进度", fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
                    activeTasks.forEach { task ->
                        Column(modifier = Modifier.padding(vertical = 4.dp)) {
                            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                Text(task.title, fontSize = 12.sp, modifier = Modifier.weight(1f), maxLines = 1)
                                Text(task.status, fontSize = 11.sp, color = if (task.isError) Color.Red else Color.Gray)
                            }
                            LinearProgressIndicator(progress = task.progress, modifier = Modifier.fillMaxWidth())
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
                            executeTasks(urls, coroutineScope, { isDownloading = it }, { activeTasks = it }, githubToken, savedPaths, context, excludeRulesText.lines().filter { it.isNotBlank() }) 
                        },
                        modifier = Modifier.weight(1f).height(48.dp),
                        enabled = !isDownloading && savedPaths.isNotEmpty(),
                        shape = RoundedCornerShape(8.dp)
                    ) { Text(name, fontSize = 13.sp, fontWeight = FontWeight.Bold) }
                }
            }
        }
    }
}

fun executeTasks(urls: List<String>, scope: kotlinx.coroutines.CoroutineScope, setDownloading: (Boolean) -> Unit, setTasks: (List<TaskState>) -> Unit, token: String, targetPaths: List<String>, context: Context, rules: List<String>) {
    scope.launch {
        setDownloading(true)
        val activeTasks = urls.map { url -> 
            val fName = url.substringAfterLast("/")
            TaskState("${if (fName.contains("dicts")) "词库包" else if (fName.contains("gram")) "模型" else "方案"} ($fName)", url) 
        }
        setTasks(activeTasks)
        for (task in activeTasks) {
            downloadAndDeployTask(task, token, targetPaths, context, rules)
            if (task.isError) break 
        }
        setDownloading(false)
    }
}

suspend fun downloadAndDeployTask(task: TaskState, token: String, targetPaths: List<String>, context: Context, rules: List<String>) {
    withContext(Dispatchers.IO) {
        val stagingDir = File(context.cacheDir, "wanxiang_staging").apply { mkdirs() }
        val tmpFile = File(stagingDir, "${task.url.substringAfterLast("/")}.tmp")
        var success = false
        var lastErrorMsg = ""

        for (attempt in 1..3) {
            try {
                withContext(Dispatchers.Main) { task.status = if (attempt > 1) "重试中($attempt/3)" else "连接中..." }
                var downloadedLen = if (tmpFile.exists()) tmpFile.length() else 0L
                val url = URL(task.url)
                val conn = url.openConnection() as HttpURLConnection
                conn.setRequestProperty("User-Agent", "WanxiangUpdater-Agent")
                
                // 请求体这里也完好保留了你的 Token 逻辑
                if (task.url.contains("github.com") && token.isNotBlank()) conn.setRequestProperty("Authorization", "Bearer $token")
                
                if (downloadedLen > 0) conn.setRequestProperty("Range", "bytes=$downloadedLen-")
                conn.connectTimeout = 10000; conn.connect()
                val isAppend = conn.responseCode == 206
                if (conn.responseCode != 200 && conn.responseCode != 206) throw Exception("HTTP ${conn.responseCode}")
                val totalSize = if (isAppend) downloadedLen + conn.contentLength.toLong() else conn.contentLength.toLong()
                conn.inputStream.use { input ->
                    FileOutputStream(tmpFile, isAppend).use { output ->
                        val data = ByteArray(16384); var count: Int
                        while (input.read(data).also { count = it } != -1) {
                            downloadedLen += count; output.write(data, 0, count)
                            withContext(Dispatchers.Main) {
                                task.progress = if (totalSize > 0) downloadedLen.toFloat() / totalSize else 0.5f
                                task.status = "${String.format("%.1f", downloadedLen/1024.0/1024.0)}MB"
                            }
                        }
                    }
                }
                success = true; break 
            } catch (e: Exception) { lastErrorMsg = e.message ?: "异常"; delay(1000) }
        }

        if (success) {
            try {
                withContext(Dispatchers.Main) { task.status = "部署中..." }
                val extractDir = File(stagingDir, "extracted_${System.currentTimeMillis()}").apply { mkdirs() }
                if (task.url.endsWith(".zip")) {
                    ZipInputStream(tmpFile.inputStream()).use { zis ->
                        var entry = zis.nextEntry
                        while (entry != null) {
                            val f = File(extractDir, entry.name)
                            if (entry.isDirectory) f.mkdirs() else { f.parentFile?.mkdirs(); FileOutputStream(f).use { zis.copyTo(it) } }
                            entry = zis.nextEntry
                        }
                    }
                } else tmpFile.copyTo(File(extractDir, task.url.substringAfterLast("/")))

                var realSrcDir = extractDir
                val subFiles = extractDir.listFiles()
                if (subFiles != null && subFiles.size == 1 && subFiles[0].isDirectory) realSrcDir = subFiles[0] 

                val excludeRegexList = rules.mapNotNull { try { Regex(it) } catch (e: Exception) { null } }
                val isDict = task.url.contains("dicts")

                for (pathStr in targetPaths) {
                    if (pathStr == "DEFAULT") {
                        val target = if (isDict) File(Environment.getExternalStorageDirectory(), "rime/dicts") else File(Environment.getExternalStorageDirectory(), "rime")
                        copyNormal(realSrcDir, target, excludeRegexList)
                    } else {
                        val rootDoc = DocumentFile.fromTreeUri(context, Uri.parse(pathStr))
                        if (rootDoc != null) {
                            val targetDoc = if (isDict) rootDoc.findFile("dicts") ?: rootDoc.createDirectory("dicts")!! else rootDoc
                            copySaf(context, realSrcDir, targetDoc, excludeRegexList)
                        }
                    }
                }
                withContext(Dispatchers.Main) { task.isFinished = true; task.status = "✅ 完成" }
            } catch (e: Exception) { withContext(Dispatchers.Main) { task.isError = true; task.status = "❌ 部署失败" } }
        } else { withContext(Dispatchers.Main) { task.isError = true; task.status = "❌ 下载失败" } }
        stagingDir.deleteRecursively()
    }
}

fun copyNormal(src: File, dest: File, rules: List<Regex>, currentPath: String = "") {
    if (!dest.exists()) dest.mkdirs()
    src.listFiles()?.forEach { file ->
        val relPath = if (currentPath.isEmpty()) file.name else "$currentPath/${file.name}"
        if (rules.any { it.containsMatchIn(relPath) } && File(dest, file.name).exists()) return@forEach
        if (file.isDirectory) copyNormal(file, File(dest, file.name), rules, relPath)
        else file.copyTo(File(dest, file.name), true)
    }
}

fun copySaf(context: Context, src: File, dest: DocumentFile, rules: List<Regex>, currentPath: String = "") {
    src.listFiles()?.forEach { file ->
        val relPath = if (currentPath.isEmpty()) file.name else "$currentPath/${file.name}"
        if (rules.any { it.containsMatchIn(relPath) } && dest.findFile(file.name) != null) return@forEach
        if (file.isDirectory) {
            val nextDest = dest.findFile(file.name) ?: dest.createDirectory(file.name)!!
            copySaf(context, file, nextDest, rules, relPath)
        } else {
            dest.findFile(file.name)?.delete()
            dest.createFile("*/*", file.name)?.let { doc -> context.contentResolver.openOutputStream(doc.uri)?.use { out -> file.inputStream().use { it.copyTo(out) } } }
        }
    }
}