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
    var updateChannel by remember { mutableStateOf("Stable") } // 新增：预览版与正式版切换
    var githubToken by remember { mutableStateOf("") }
    
    var isDownloading by remember { mutableStateOf(false) }
    var activeTasks by remember { mutableStateOf<List<TaskState>>(emptyList()) }
    val coroutineScope = rememberCoroutineScope()

    val auxMap = mapOf(
        "zrm" to "自然码", "flypy" to "小鹤", "moqi" to "墨奇",
        "hanxin" to "汉心", "shouyou" to "首右", "tiger" to "虎码", "wubi" to "五笔"
    )

    Column(modifier = Modifier.padding(16.dp).verticalScroll(rememberScrollState())) {
        Text("📱 万象拼音更新器", fontSize = 24.sp, fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
        Text("v1.0 • 万象更新 & SAF写入", fontSize = 12.sp, color = Color.Gray)
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
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = if (customRimeUri == null) "默认: 手机根目录 /rime" else "自定义: 已通过系统授权",
                    fontSize = 13.sp, color = Color.DarkGray, maxLines = 2, overflow = TextOverflow.Ellipsis
                )
                Spacer(modifier = Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(
                        onClick = onSelectCustomDir,
                        modifier = Modifier.weight(1f).height(36.dp),
                        contentPadding = PaddingValues(0.dp)
                    ) { Text("选择自定义目录", fontSize = 12.sp) }
                    
                    if (customRimeUri != null) {
                        TextButton(
                            onClick = onResetDir,
                            modifier = Modifier.height(36.dp),
                            contentPadding = PaddingValues(horizontal = 8.dp)
                        ) { Text("恢复默认", fontSize = 12.sp, color = Color.Gray) }
                    }
                }
            }
        }
        Spacer(modifier = Modifier.height(12.dp))

        // 方案与通道选择卡片
        Card(
            colors = CardDefaults.cardColors(containerColor = Color.White),
            border = CardDefaults.outlinedCardBorder(true),
            elevation = CardDefaults.cardElevation(2.dp),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                
                // 🌟 新增：预览版/正式版 通道切换
                Text("🚀 更新通道", fontWeight = FontWeight.Bold, color = Color.DarkGray)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = updateChannel == "Stable", onClick = { updateChannel = "Stable" })
                    Text("正式版", fontSize = 14.sp)
                    Spacer(modifier = Modifier.width(16.dp))
                    RadioButton(selected = updateChannel == "Preview", onClick = { updateChannel = "Preview" })
                    Text("预览版", fontSize = 14.sp, color = MorandiGreen)
                }
                
                Divider(color = MorandiLightGreen, modifier = Modifier.padding(vertical = 8.dp))
                
                Text("📦 方案版本", fontWeight = FontWeight.Bold, color = Color.DarkGray)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = isPro, onClick = { isPro = true; if(!isPro) auxScheme="zrm" })
                    Text("Pro版 (辅助码)", fontSize = 14.sp)
                    Spacer(modifier = Modifier.width(16.dp))
                    RadioButton(selected = !isPro, onClick = { isPro = false })
                    Text("Base版 (纯拼音)", fontSize = 14.sp)
                }

                if (isPro) {
                    Divider(color = MorandiLightGreen, modifier = Modifier.padding(vertical = 8.dp))
                    Text("⌨️ 辅助码方案:", fontSize = 13.sp, color = Color.Gray)
                    FlowRow(
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp)
                    ) {
                        auxMap.forEach { (key, name) ->
                            FilterChip(
                                selected = (auxScheme == key),
                                onClick = { auxScheme = key },
                                label = { Text(name, fontSize = 12.sp) },
                                colors = FilterChipDefaults.filterChipColors(
                                    selectedContainerColor = MorandiLightGreen,
                                    selectedLabelColor = MorandiDarkGreen
                                )
                            )
                        }
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        // 下载源卡片
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
                    Text("CNB (国内快)", fontSize = 14.sp)
                    Spacer(modifier = Modifier.width(8.dp))
                    RadioButton(selected = downloadSource == "GitHub", onClick = { downloadSource = "GitHub" })
                    Text("GitHub (官方)", fontSize = 14.sp)
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

        // 🌟 核心：根据【正式版/预览版】动态生成链接
        val schemeStr = if (isPro) auxScheme else "base"
        val versionTag = if (updateChannel == "Stable") "v1.0.0" else "preview" // <-- 这里可以按需修改你的预览版 Tag
        val ghVersionTag = if (updateChannel == "Stable") "dict-nightly" else "preview"
        
        val cnbBase = "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/$versionTag"
        val cnbModel = "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/model"
        val ghBase = "https://github.com/amzxyz/rime_wanxiang/releases/download/$ghVersionTag"
        val ghModel = "https://github.com/amzxyz/RIME-LMDG/releases/download/LTS"

        val schemaUrl = if (downloadSource == "CNB") "$cnbBase/rime-wanxiang-$schemeStr${if(isPro) "-fuzhu" else ""}.zip" else "$ghBase/rime-wanxiang-$schemeStr${if(isPro) "-fuzhu" else ""}.zip"
        val dictUrl = if (downloadSource == "CNB") "$cnbBase/${if(isPro) "pro-$schemeStr-fuzhu" else "base"}-dicts.zip" else "$ghBase/${if(isPro) "pro-$schemeStr-fuzhu" else "base"}-dicts.zip"
        val modelUrl = if (downloadSource == "CNB") "$cnbModel/wanxiang-lts-zh-hans.gram" else "$ghModel/wanxiang-lts-zh-hans.gram"

        val tasksMap = listOf(
            "🚀 全量更新" to listOf(schemaUrl, dictUrl, modelUrl),
            "⚙️ 仅方案组件" to listOf(schemaUrl),
            "📖 仅词库组件" to listOf(dictUrl),
            "🧠 仅语法模型" to listOf(modelUrl)
        )

        AnimatedVisibility(visible = activeTasks.isNotEmpty()) {
            Card(
                colors = CardDefaults.cardColors(containerColor = MorandiLightGreen),
                border = CardDefaults.outlinedCardBorder(true),
                modifier = Modifier.fillMaxWidth().padding(bottom = 16.dp)
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("📥 任务进度", fontWeight = FontWeight.Bold, color = MorandiDarkGreen, modifier = Modifier.padding(bottom = 8.dp))
                    activeTasks.forEach { task ->
                        Column(modifier = Modifier.padding(vertical = 6.dp)) {
                            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                Text(task.title, fontSize = 13.sp, fontWeight = FontWeight.Bold, color = Color.DarkGray, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                                Text(task.status, fontSize = 12.sp, color = if (task.isError) Color.Red else if (task.isFinished) MorandiGreen else Color.Gray)
                            }
                            Spacer(modifier = Modifier.height(4.dp))
                            LinearProgressIndicator(
                                progress = task.progress,
                                modifier = Modifier.fillMaxWidth().height(6.dp),
                                color = if (task.isError) Color.Red else MorandiGreen,
                                trackColor = Color(0xFFD5E3D6)
                            )
                        }
                    }
                }
            }
        }

        Text("执行下载与覆盖:", fontWeight = FontWeight.Bold, color = Color.DarkGray, modifier = Modifier.padding(bottom = 8.dp))
        
        Column(modifier = Modifier.fillMaxWidth()) {
            for (i in tasksMap.indices step 2) {
                Row(modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    val task1 = tasksMap[i]
                    Button(
                        onClick = { executeTasks(task1.second, coroutineScope, { isDownloading = it }, { activeTasks = it }, githubToken, customRimeUri, context) },
                        modifier = Modifier.weight(1f).height(48.dp),
                        enabled = !isDownloading,
                        colors = ButtonDefaults.buttonColors(containerColor = MorandiGreen),
                        shape = RoundedCornerShape(8.dp)
                    ) { Text(task1.first, fontSize = 14.sp, fontWeight = FontWeight.Bold) }

                    if (i + 1 < tasksMap.size) {
                        val task2 = tasksMap[i + 1]
                        Button(
                            onClick = { executeTasks(task2.second, coroutineScope, { isDownloading = it }, { activeTasks = it }, githubToken, customRimeUri, context) },
                            modifier = Modifier.weight(1f).height(48.dp),
                            enabled = !isDownloading,
                            colors = ButtonDefaults.buttonColors(containerColor = MorandiGreen),
                            shape = RoundedCornerShape(8.dp)
                        ) { Text(task2.first, fontSize = 14.sp, fontWeight = FontWeight.Bold) }
                    } else {
                        Spacer(modifier = Modifier.weight(1f))
                    }
                }
            }
        }
        Spacer(modifier = Modifier.height(30.dp))
    }
}

fun executeTasks(
    urls: List<String>, scope: kotlinx.coroutines.CoroutineScope,
    setDownloading: (Boolean) -> Unit, setTasks: (List<TaskState>) -> Unit,
    token: String, customUri: Uri?, context: Context
) {
    scope.launch {
        setDownloading(true)
        val activeTasks = urls.map { url -> 
            val fName = url.substringAfterLast("/")
            val title = when {
                fName.contains("dicts") -> "词库包 ($fName)"
                fName.contains("gram") -> "语法模型 ($fName)"
                else -> "主方案 ($fName)"
            }
            TaskState(title, url) 
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
        
        // 把战场转移到 App 内部的私有缓存目录，绝对有权限！
        val stagingDir = File(context.cacheDir, "wanxiang_staging")
        if (stagingDir.exists()) stagingDir.deleteRecursively()
        stagingDir.mkdirs()

        val fileName = task.url.substringAfterLast("/")
        val tmpFile = File(stagingDir, "$fileName.tmp")
        
        val maxRetries = 3
        var success = false
        var lastErrorMsg = ""

        for (attempt in 1..maxRetries) {
            try {
                withContext(Dispatchers.Main) {
                    task.status = if (attempt > 1) "重试中($attempt/$maxRetries)..." else "连接中..."
                }
                var downloadedLen = if (tmpFile.exists()) tmpFile.length() else 0L

                val url = URL(task.url)
                val connection = url.openConnection() as HttpURLConnection
                connection.setRequestProperty("User-Agent", "Rime-Wanxiang-Android")
                if (task.url.contains("github.com") && token.isNotBlank()) {
                    connection.setRequestProperty("Authorization", "Bearer $token")
                }
                if (downloadedLen > 0) connection.setRequestProperty("Range", "bytes=$downloadedLen-")
                connection.connect()

                val responseCode = connection.responseCode
                val isAppend = (responseCode == HttpURLConnection.HTTP_PARTIAL)
                
                if (responseCode != HttpURLConnection.HTTP_OK && responseCode != HttpURLConnection.HTTP_PARTIAL) {
                    if (responseCode == 416) { tmpFile.delete(); continue }
                    throw Exception("网络错误码: $responseCode")
                }

                if (!isAppend && downloadedLen > 0) {
                    downloadedLen = 0L; tmpFile.delete()
                }

                val contentLength = connection.contentLength.toLong()
                val totalSize = if (contentLength < 0) -1L else if (isAppend) downloadedLen + contentLength else contentLength

                val input = connection.inputStream
                // 这里绝对不会报错，因为是在沙盒私有目录
                val output = FileOutputStream(tmpFile, isAppend)

                val data = ByteArray(16384)
                var count: Int
                var lastReportTime = System.currentTimeMillis()

                while (input.read(data).also { count = it } != -1) {
                    downloadedLen += count
                    output.write(data, 0, count)
                    
                    val now = System.currentTimeMillis()
                    if (totalSize > 0 && now - lastReportTime > 200) {
                        val pct = downloadedLen.toFloat() / totalSize.toFloat()
                        val mbStr = String.format("%.1f", downloadedLen / 1024.0 / 1024.0)
                        val totStr = String.format("%.1f", totalSize / 1024.0 / 1024.0)
                        withContext(Dispatchers.Main) {
                            task.progress = pct
                            task.status = "下载中: $mbStr / $totStr MB"
                        }
                        lastReportTime = now
                    }
                }
                output.flush(); output.close(); input.close()
                if (totalSize > 0 && tmpFile.length() < totalSize) throw Exception("下载断流")
                success = true
                break
            } catch (e: Exception) {
                lastErrorMsg = e.javaClass.simpleName + ": " + (e.message ?: "未知异常")
                e.printStackTrace()
                delay(1500)
            }
        }

        if (!success) {
            withContext(Dispatchers.Main) { task.isError = true; task.status = "❌ 下载失败: $lastErrorMsg" }
            return@withContext
        }

        try {
            withContext(Dispatchers.Main) { task.status = "正在解压部署..."; task.progress = 1.0f }
            
            // 在私有缓存目录里原地解压
            val extractDir = File(stagingDir, "extracted")
            extractDir.mkdirs()
            val isDictZip = fileName.contains("dicts")

            if (fileName.endsWith(".zip")) {
                ZipInputStream(tmpFile.inputStream()).use { zis ->
                    var entry = zis.nextEntry
                    while (entry != null) {
                        val file = File(extractDir, entry.name)
                        if (entry.isDirectory) {
                            file.mkdirs()
                        } else {
                            file.parentFile?.mkdirs()
                            FileOutputStream(file).use { fos -> zis.copyTo(fos) }
                        }
                        zis.closeEntry()
                        entry = zis.nextEntry
                    }
                }
            } else {
                tmpFile.copyTo(File(extractDir, fileName))
            }

            // 根据用户选择，走不同的传输通道
            if (customUri != null) {
                // 通道 A：SAF 协议传输（专治 Android/data 拒绝访问）
                val rootDoc = DocumentFile.fromTreeUri(context, customUri) ?: throw Exception("无法挂载授权目录")
                val targetDoc = if (isDictZip) {
                    rootDoc.findFile("dicts") ?: rootDoc.createDirectory("dicts") ?: throw Exception("无法创建 dicts 文件夹")
                } else rootDoc

                // 用 SAF 的方式递归复制过去
                fun copyToSaf(src: File, dest: DocumentFile) {
                    src.listFiles()?.forEach { file ->
                        if (file.isDirectory) {
                            val nextDest = dest.findFile(file.name) ?: dest.createDirectory(file.name)
                            if (nextDest != null) copyToSaf(file, nextDest)
                        } else {
                            // 遇到同名文件先删除，确保覆盖
                            dest.findFile(file.name)?.delete()
                            val targetFile = dest.createFile("*/*", file.name)
                            targetFile?.let { doc ->
                                context.contentResolver.openOutputStream(doc.uri)?.use { out ->
                                    file.inputStream().use { input -> input.copyTo(out) }
                                }
                            }
                        }
                    }
                }
                copyToSaf(extractDir, targetDoc)
                
            } else {
                // 通道 B：经典根目录传输（仅需普通文件管理权限）
                val rimeDir = File(Environment.getExternalStorageDirectory(), "rime")
                val targetDir = if (isDictZip) File(rimeDir, "dicts") else rimeDir
                if (!targetDir.exists()) targetDir.mkdirs()
                extractDir.copyRecursively(targetDir, overwrite = true)
            }

            // 打扫战场
            stagingDir.deleteRecursively()

            withContext(Dispatchers.Main) { task.isFinished = true; task.status = "✅ 部署完成" }
        } catch (e: Exception) {
            e.printStackTrace()
            withContext(Dispatchers.Main) { 
                task.isError = true
                task.status = "❌ 写入异常: ${e.javaClass.simpleName} - ${e.message}" 
            }
        }
    }
}