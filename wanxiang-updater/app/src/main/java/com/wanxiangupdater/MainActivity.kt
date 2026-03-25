package com.wanxiangupdater

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import androidx.activity.ComponentActivity
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

// 🌟 对齐：默认的防覆盖正则列表（完美复刻你的 Python 脚本）
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
    var customRimeUri by mutableStateOf<Uri?>(null)
    private val dirPickerLauncher = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
            customRimeUri = uri
        }
    }

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
                    WanxiangDownloaderApp(
                        customRimeUri = customRimeUri,
                        onSelectCustomDir = { dirPickerLauncher.launch(null) },
                        onResetDir = { customRimeUri = null }
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun WanxiangDownloaderApp(
    customRimeUri: Uri?,
    onSelectCustomDir: () -> Unit,
    onResetDir: () -> Unit
) {
    val context = LocalContext.current
    val sharedPref = context.getSharedPreferences("WanxiangPrefs", Context.MODE_PRIVATE)

    // 对齐：优雅的权限解释弹窗
    var showPermissionDialog by remember { 
        mutableStateOf(Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && !Environment.isExternalStorageManager()) 
    }

    if (showPermissionDialog) {
        AlertDialog(
            onDismissRequest = { /* 必须做出选择 */ },
            title = { Text("需要存储访问权限", fontWeight = FontWeight.Bold, fontSize = 18.sp, color = MorandiDarkGreen) },
            text = {
                // 🚨 修复了你发来的代码里这里漏掉逗号导致报错的问题
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
    var githubToken by remember { mutableStateOf("") }
    
    // 🌟 对齐：读取本地保存的正则规则
    var excludeRulesText by remember { 
        mutableStateOf(sharedPref.getString("exclude_rules", DEFAULT_EXCLUDE_RULES) ?: DEFAULT_EXCLUDE_RULES) 
    }
    var showAdvancedRules by remember { mutableStateOf(false) }

    // 动态版本探测引擎
    var latestStableTag by remember { mutableStateOf("v1.0.0") }
    LaunchedEffect(Unit) {
        withContext(Dispatchers.IO) {
            try {
                val url = URL("https://api.github.com/repos/amzxyz/rime_wanxiang/releases/latest")
                val conn = url.openConnection() as HttpURLConnection
                conn.connect()
                if (conn.responseCode == 200) {
                    val content = conn.inputStream.bufferedReader().readText()
                    val regex = Regex("\"tag_name\"\\s*:\\s*\"([^\"]+)\"")
                    regex.find(content)?.groupValues?.get(1)?.let { latestStableTag = it }
                }
            } catch (e: Exception) { e.printStackTrace() }
        }
    }

    var isDownloading by remember { mutableStateOf(false) }
    var activeTasks by remember { mutableStateOf<List<TaskState>>(emptyList()) }
    val coroutineScope = rememberCoroutineScope()

    val auxMap = mapOf(
        "zrm" to "自然码", "flypy" to "小鹤", "moqi" to "墨奇",
        "hanxin" to "汉心", "shouyou" to "首右", "tiger" to "虎码", "wubi" to "五笔"
    )

    Column(modifier = Modifier.padding(16.dp).verticalScroll(rememberScrollState())) {
        Text("📱 万象拼音更新器", fontSize = 24.sp, fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
        Text("v1.8 • 权限提示与护盾全开", fontSize = 12.sp, color = Color.Gray)
        Spacer(modifier = Modifier.height(16.dp))

        // 部署路径卡片
        Card(colors = CardDefaults.cardColors(containerColor = MorandiLightGreen), border = CardDefaults.outlinedCardBorder(true), modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text("📁 部署路径", fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
                Text(text = if (customRimeUri == null) "默认: 手机根目录 /rime" else "自定义: 已通过系统授权", fontSize = 13.sp, color = Color.DarkGray)
                Spacer(modifier = Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = onSelectCustomDir, modifier = Modifier.weight(1f).height(36.dp)) { Text("选择自定义目录", fontSize = 12.sp) }
                    if (customRimeUri != null) {
                        TextButton(onClick = onResetDir) { Text("恢复默认", fontSize = 12.sp, color = Color.Gray) }
                    }
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
                    RadioButton(selected = isPro, onClick = { isPro = true })
                    Text("Pro版 (辅助码)", fontSize = 14.sp)
                    Spacer(modifier = Modifier.width(16.dp))
                    RadioButton(selected = !isPro, onClick = { isPro = false })
                    Text("Base版 (纯拼音)", fontSize = 14.sp)
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

        // 🌟 对齐：高级保护规则面板（赋予用户自定义能力）
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
                        Text("如果解压的文件相对路径匹配以下正则，且本地已有该文件，将强制跳过覆盖。每行一个规则：", fontSize = 11.sp, color = Color.Gray, modifier = Modifier.padding(bottom = 8.dp))
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
                        ) { Text("恢复默认规则", fontSize = 12.sp, color = Color.Red) }
                    }
                }
            }
        }
        Spacer(modifier = Modifier.height(12.dp))

        // 下载源配置
        Card(colors = CardDefaults.cardColors(containerColor = Color.White), border = CardDefaults.outlinedCardBorder(true), modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text("🌐 下载源配置", fontWeight = FontWeight.Bold, color = Color.DarkGray)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = downloadSource == "CNB", onClick = { downloadSource = "CNB" })
                    Text("CNB", fontSize = 14.sp)
                    Spacer(modifier = Modifier.width(8.dp))
                    RadioButton(selected = downloadSource == "GitHub", onClick = { downloadSource = "GitHub" })
                    Text("GitHub", fontSize = 14.sp)
                }
                if (downloadSource == "GitHub") {
                    OutlinedTextField(
                        value = githubToken, onValueChange = { githubToken = it },
                        label = { Text("GitHub Token (可选, 防限流)", fontSize = 12.sp) },
                        visualTransformation = PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        modifier = Modifier.fillMaxWidth().height(60.dp), singleLine = true
                    )
                }
            }
        }
        Spacer(modifier = Modifier.height(16.dp))

        // 🔗 核心链接生成逻辑
        val schemeStr = if (isPro) auxScheme else "base"
        val cnbTag = if (updateChannel == "Stable") latestStableTag else "v1.0.0"
        val ghTag = if (updateChannel == "Stable") latestStableTag else "dict-nightly"
        val activeTag = if (downloadSource == "CNB") cnbTag else ghTag
        val baseDownloadUrl = if (downloadSource == "CNB") "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/$activeTag" else "https://github.com/amzxyz/rime_wanxiang/releases/download/$activeTag"
        
        // 🚨 词库强制分流
        val dictTag = if (downloadSource == "CNB") "v1.0.0" else "dict-nightly"
        val dictBaseUrl = if (downloadSource == "CNB") "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/$dictTag" else "https://github.com/amzxyz/rime_wanxiang/releases/download/$dictTag"

        val schemaUrl = "$baseDownloadUrl/rime-wanxiang-$schemeStr${if(isPro) "-fuzhu" else ""}.zip"
        val dictUrl = "$dictBaseUrl/${if(isPro) "pro-$schemeStr-fuzhu" else "base"}-dicts.zip"
        val modelUrl = if (downloadSource == "CNB") "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/model/wanxiang-lts-zh-hans.gram" else "https://github.com/amzxyz/RIME-LMDG/releases/download/LTS/wanxiang-lts-zh-hans.gram"

        val tasksMap = listOf(
            "🚀 全量更新" to listOf(schemaUrl, dictUrl, modelUrl),
            "⚙️ 仅方案组件" to listOf(schemaUrl),
            "📖 仅词库组件" to listOf(dictUrl),
            "🧠 仅语法模型" to listOf(modelUrl)
        )

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
                            // 🌟 传递动态获取的规则列表给下载引擎
                            val currentRules = excludeRulesText.lines().filter { it.isNotBlank() }
                            executeTasks(urls, coroutineScope, { isDownloading = it }, { activeTasks = it }, githubToken, customRimeUri, context, currentRules) 
                        },
                        modifier = Modifier.weight(1f).height(48.dp),
                        enabled = !isDownloading,
                        shape = RoundedCornerShape(8.dp)
                    ) { Text(name, fontSize = 13.sp, fontWeight = FontWeight.Bold) }
                }
            }
        }
    }
}

fun executeTasks(urls: List<String>, scope: kotlinx.coroutines.CoroutineScope, setDownloading: (Boolean) -> Unit, setTasks: (List<TaskState>) -> Unit, token: String, customUri: Uri?, context: Context, rules: List<String>) {
    scope.launch {
        setDownloading(true)
        val activeTasks = urls.map { url -> 
            val fName = url.substringAfterLast("/")
            val title = when {
                fName.contains("dicts") -> "词库包"
                fName.contains("gram") -> "模型"
                else -> "方案"
            }
            TaskState("$title ($fName)", url) 
        }
        setTasks(activeTasks)
        for (task in activeTasks) {
            downloadAndDeployTask(task, token, customUri, context, rules)
            if (task.isError) break 
        }
        setDownloading(false)
    }
}

suspend fun downloadAndDeployTask(task: TaskState, token: String, customUri: Uri?, context: Context, rules: List<String>) {
    withContext(Dispatchers.IO) {
        val stagingDir = File(context.cacheDir, "wanxiang_staging")
        if (!stagingDir.exists()) stagingDir.mkdirs()
        
        val fileName = task.url.substringAfterLast("/")
        val tmpFile = File(stagingDir, "$fileName.tmp")
        
        var success = false
        var lastErrorMsg = ""

        // 🌟 对齐：真·断点续传与 3 次重试机制
        for (attempt in 1..3) {
            try {
                withContext(Dispatchers.Main) { task.status = if (attempt > 1) "重试中($attempt/3)" else "连接中..." }
                var downloadedLen = if (tmpFile.exists()) tmpFile.length() else 0L

                val url = URL(task.url)
                val conn = url.openConnection() as HttpURLConnection
                conn.setRequestProperty("User-Agent", "Rime-Wanxiang-Android")
                if (task.url.contains("github.com") && token.isNotBlank()) {
                    conn.setRequestProperty("Authorization", "Bearer $token")
                }
                
                if (downloadedLen > 0) conn.setRequestProperty("Range", "bytes=$downloadedLen-")
                conn.connect()

                val responseCode = conn.responseCode
                val isAppend = responseCode == HttpURLConnection.HTTP_PARTIAL
                
                if (responseCode != 200 && responseCode != 206) {
                    if (responseCode == 416) { tmpFile.delete(); continue } 
                    throw Exception("HTTP $responseCode")
                }
                
                if (!isAppend && downloadedLen > 0) {
                    downloadedLen = 0L
                    tmpFile.delete()
                }

                val contentLength = conn.contentLength.toLong()
                val totalSize = if (contentLength < 0) -1L else if (isAppend) downloadedLen + contentLength else contentLength

                conn.inputStream.use { input ->
                    FileOutputStream(tmpFile, isAppend).use { output ->
                        val data = ByteArray(16384)
                        var count: Int
                        while (input.read(data).also { count = it } != -1) {
                            downloadedLen += count
                            output.write(data, 0, count)
                            withContext(Dispatchers.Main) {
                                task.progress = if (totalSize > 0) downloadedLen.toFloat() / totalSize else 0.5f
                                task.status = "${String.format("%.1f", downloadedLen/1024.0/1024.0)}MB"
                            }
                        }
                    }
                }
                success = true
                break 
            } catch (e: Exception) {
                lastErrorMsg = e.message ?: "网络异常"
                delay(1000)
            }
        }

        if (!success) {
            withContext(Dispatchers.Main) { task.isError = true; task.status = "❌ 下载失败: $lastErrorMsg" }
            return@withContext
        }

        try {
            withContext(Dispatchers.Main) { task.status = "正在解压..." }
            val extractDir = File(stagingDir, "extracted_${System.currentTimeMillis()}").apply { mkdirs() }
            
            if (fileName.endsWith(".zip")) {
                ZipInputStream(tmpFile.inputStream()).use { zis ->
                    var entry = zis.nextEntry
                    while (entry != null) {
                        val f = File(extractDir, entry.name)
                        if (entry.isDirectory) f.mkdirs() else {
                            f.parentFile?.mkdirs()
                            FileOutputStream(f).use { zis.copyTo(it) }
                        }
                        entry = zis.nextEntry
                    }
                }
            } else tmpFile.copyTo(File(extractDir, fileName))

            // 🌟 对齐：智能去套娃
            var realSrcDir = extractDir
            val subFiles = extractDir.listFiles()
            if (subFiles != null && subFiles.size == 1 && subFiles[0].isDirectory) {
                realSrcDir = subFiles[0] 
            }

            withContext(Dispatchers.Main) { task.status = "正在覆盖部署..." }
            
            // 🌟 对齐：动态编译用户的正则，并带有相对路径处理 (防崩溃设计)
            val excludeRegexList = rules.mapNotNull { 
                try { Regex(it) } catch (e: Exception) { null } 
            }

            if (customUri != null) {
                val rootDoc = DocumentFile.fromTreeUri(context, customUri) ?: throw Exception("授权失效")
                val isDict = task.url.contains("dicts")
                val targetDoc = if (isDict) rootDoc.findFile("dicts") ?: rootDoc.createDirectory("dicts")!! else rootDoc
                
                fun copySaf(src: File, dest: DocumentFile, currentPath: String = "") {
                    src.listFiles()?.forEach { file ->
                        // 动态获取相对路径用于正则验证 (例如: "custom/my.yaml" 或 "sync/log.txt")
                        val relPath = if (currentPath.isEmpty()) file.name else "$currentPath/${file.name}"
                        
                        // 🛡️ 护盾触发
                        if (excludeRegexList.any { it.containsMatchIn(relPath) } && dest.findFile(file.name) != null) {
                            return@forEach 
                        }

                        if (file.isDirectory) {
                            val nextDest = dest.findFile(file.name) ?: dest.createDirectory(file.name)!!
                            copySaf(file, nextDest, relPath)
                        } else {
                            dest.findFile(file.name)?.delete() 
                            dest.createFile("*/*", file.name)?.let { doc ->
                                context.contentResolver.openOutputStream(doc.uri)?.use { out -> 
                                    file.inputStream().use { it.copyTo(out) } 
                                }
                            }
                        }
                    }
                }
                copySaf(realSrcDir, targetDoc)
            } else {
                val rimeDir = File(Environment.getExternalStorageDirectory(), "rime")
                val target = if (task.url.contains("dicts")) File(rimeDir, "dicts") else rimeDir
                if (!target.exists()) target.mkdirs()
                
                fun copyNormal(src: File, dest: File, currentPath: String = "") {
                    src.listFiles()?.forEach { file ->
                        val relPath = if (currentPath.isEmpty()) file.name else "$currentPath/${file.name}"
                        val targetFile = File(dest, file.name)
                        
                        // 🛡️ 护盾触发
                        if (excludeRegexList.any { it.containsMatchIn(relPath) } && targetFile.exists()) {
                            return@forEach
                        }
                        
                        if (file.isDirectory) {
                            targetFile.mkdirs()
                            copyNormal(file, targetFile, relPath)
                        } else {
                            file.copyTo(targetFile, overwrite = true)
                        }
                    }
                }
                copyNormal(realSrcDir, target)
            }
            
            withContext(Dispatchers.Main) { task.isFinished = true; task.status = "✅ 部署完成" }
            tmpFile.delete() 
        } catch (e: Exception) {
            e.printStackTrace()
            withContext(Dispatchers.Main) { task.isError = true; task.status = "❌ 部署失败" }
        } finally {
            stagingDir.deleteRecursively()
        }
    }
}