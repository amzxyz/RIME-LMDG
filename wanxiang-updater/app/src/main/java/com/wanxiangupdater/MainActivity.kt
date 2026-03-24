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
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && !Environment.isExternalStorageManager()) {
            val intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
            intent.data = Uri.parse("package:$packageName")
            startActivity(intent)
        }
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
    var isPro by remember { mutableStateOf(true) }
    var auxScheme by remember { mutableStateOf("zrm") }
    var downloadSource by remember { mutableStateOf("CNB") }
    var updateChannel by remember { mutableStateOf("Stable") } 
    var githubToken by remember { mutableStateOf("") }
    
    // 🌟 动态版本探测引擎
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
        Text("v1.1 • 动态版本解析", fontSize = 12.sp, color = Color.Gray)
        Spacer(modifier = Modifier.height(16.dp))

        // 部署路径卡片
        Card(
            colors = CardDefaults.cardColors(containerColor = MorandiLightGreen),
            border = CardDefaults.outlinedCardBorder(true),
            elevation = CardDefaults.cardElevation(2.dp),
            modifier = Modifier.fillMaxWidth()
        ) {
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
        Card(
            colors = CardDefaults.cardColors(containerColor = Color.White),
            border = CardDefaults.outlinedCardBorder(true),
            elevation = CardDefaults.cardElevation(2.dp),
            modifier = Modifier.fillMaxWidth()
        ) {
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
                            FilterChip(
                                selected = (auxScheme == key),
                                onClick = { auxScheme = key },
                                label = { Text(name, fontSize = 12.sp) }
                            )
                        }
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        // 下载源
        Card(
            colors = CardDefaults.cardColors(containerColor = Color.White),
            border = CardDefaults.outlinedCardBorder(true),
            elevation = CardDefaults.cardElevation(2.dp),
            modifier = Modifier.fillMaxWidth()
        ) {
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
                        value = githubToken,
                        onValueChange = { githubToken = it },
                        label = { Text("GitHub Token (可选, 防限流)", fontSize = 12.sp) },
                        visualTransformation = PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        modifier = Modifier.fillMaxWidth().height(60.dp),
                        singleLine = true,
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = MorandiGreen,
                            focusedLabelColor = MorandiDarkGreen
                        )
                    )
                }
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        // 🔗 核心链接生成逻辑
        val schemeStr = if (isPro) auxScheme else "base"
        
        // 🚦 主方案分流：正式版用嗅探的 Tag，预览版用固定 Tag
        val cnbTag = if (updateChannel == "Stable") latestStableTag else "v1.0.0"
        val ghTag = if (updateChannel == "Stable") latestStableTag else "dict-nightly"

        val activeTag = if (downloadSource == "CNB") cnbTag else ghTag
        val baseDownloadUrl = if (downloadSource == "CNB") 
            "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/$activeTag"
            else "https://github.com/amzxyz/rime_wanxiang/releases/download/$activeTag"

        // 🚨 词库强制分流：无论正式还是预览，词库永远走固定的预览版标签
        val dictTag = if (downloadSource == "CNB") "v1.0.0" else "dict-nightly"
        val dictBaseUrl = if (downloadSource == "CNB") 
            "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/$dictTag"
            else "https://github.com/amzxyz/rime_wanxiang/releases/download/$dictTag"

        // 组装最终链接
        val schemaUrl = "$baseDownloadUrl/rime-wanxiang-$schemeStr${if(isPro) "-fuzhu" else ""}.zip"
        val dictUrl = "$dictBaseUrl/${if(isPro) "pro-$schemeStr-fuzhu" else "base"}-dicts.zip"
        val modelUrl = if (downloadSource == "CNB") 
            "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/model/wanxiang-lts-zh-hans.gram"
            else "https://github.com/amzxyz/RIME-LMDG/releases/download/LTS/wanxiang-lts-zh-hans.gram"

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
                        onClick = { executeTasks(urls, coroutineScope, { isDownloading = it }, { activeTasks = it }, githubToken, customRimeUri, context) },
                        modifier = Modifier.weight(1f).height(48.dp),
                        enabled = !isDownloading,
                        shape = RoundedCornerShape(8.dp)
                    ) { Text(name, fontSize = 13.sp, fontWeight = FontWeight.Bold) }
                }
            }
        }
    }
}

fun executeTasks(urls: List<String>, scope: kotlinx.coroutines.CoroutineScope, setDownloading: (Boolean) -> Unit, setTasks: (List<TaskState>) -> Unit, token: String, customUri: Uri?, context: Context) {
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
            downloadAndDeployTask(task, token, customUri, context)
            if (task.isError) break 
        }
        setDownloading(false)
    }
}

suspend fun downloadAndDeployTask(task: TaskState, token: String, customUri: Uri?, context: Context) {
    withContext(Dispatchers.IO) {
        val stagingDir = File(context.cacheDir, "wanxiang_staging")
        if (stagingDir.exists()) stagingDir.deleteRecursively()
        stagingDir.mkdirs()
        val fileName = task.url.substringAfterLast("/")
        val tmpFile = File(stagingDir, "$fileName.tmp")
        
        var success = false
        try {
            val url = URL(task.url)
            val conn = url.openConnection() as HttpURLConnection
            conn.setRequestProperty("User-Agent", "Rime-Wanxiang-Android")
            
            // 🚨 修复点：这下 GitHub Token 终于起效了！
            if (task.url.contains("github.com") && token.isNotBlank()) {
                conn.setRequestProperty("Authorization", "Bearer $token")
            }
            
            conn.connect()
            if (conn.responseCode != 200) throw Exception("HTTP ${conn.responseCode}")
            
            val totalSize = conn.contentLength.toLong()
            conn.inputStream.use { input ->
                FileOutputStream(tmpFile).use { output ->
                    val data = ByteArray(16384)
                    var downloaded = 0L
                    var count: Int
                    while (input.read(data).also { count = it } != -1) {
                        downloaded += count
                        output.write(data, 0, count)
                        withContext(Dispatchers.Main) {
                            task.progress = downloaded.toFloat() / totalSize
                            task.status = "${String.format("%.1f", downloaded/1024.0/1024.0)}MB"
                        }
                    }
                }
            }
            success = true
        } catch (e: Exception) {
            withContext(Dispatchers.Main) { task.isError = true; task.status = "❌ 下载失败: ${e.message}" }
        }

        if (success) {
            try {
                withContext(Dispatchers.Main) { task.status = "正在部署..." }
                val extractDir = File(stagingDir, "extracted").apply { mkdirs() }
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

                if (customUri != null) {
                    val rootDoc = DocumentFile.fromTreeUri(context, customUri)!!
                    val targetDoc = if (fileName.contains("dicts")) rootDoc.findFile("dicts") ?: rootDoc.createDirectory("dicts")!! else rootDoc
                    fun copySaf(src: File, dest: DocumentFile) {
                        src.listFiles()?.forEach { file ->
                            if (file.isDirectory) copySaf(file, dest.findFile(file.name) ?: dest.createDirectory(file.name)!!)
                            else {
                                dest.findFile(file.name)?.delete()
                                dest.createFile("*/*", file.name)?.let { doc ->
                                    context.contentResolver.openOutputStream(doc.uri)?.use { out -> file.inputStream().use { it.copyTo(out) } }
                                }
                            }
                        }
                    }
                    copySaf(extractDir, targetDoc)
                } else {
                    val rimeDir = File(Environment.getExternalStorageDirectory(), "rime")
                    val target = if (fileName.contains("dicts")) File(rimeDir, "dicts") else rimeDir
                    extractDir.copyRecursively(target, true)
                }
                withContext(Dispatchers.Main) { task.isFinished = true; task.status = "✅ 完成" }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) { task.isError = true; task.status = "❌ 部署失败" }
            }
        }
        stagingDir.deleteRecursively()
    }
}