package com.wanxiangupdater

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
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
                    WanxiangDownloaderApp()
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun WanxiangDownloaderApp() {
    var isPro by remember { mutableStateOf(true) }
    var auxScheme by remember { mutableStateOf("zrm") }
    var downloadSource by remember { mutableStateOf("CNB") }
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
        Text("v1.1 • 断点续传 & 智能解压引擎", fontSize = 12.sp, color = Color.Gray)
        Spacer(modifier = Modifier.height(16.dp))

        Card(
            colors = CardDefaults.cardColors(containerColor = Color.White),
            border = CardDefaults.outlinedCardBorder(true),
            elevation = CardDefaults.cardElevation(2.dp),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
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

        val schemeStr = if (isPro) auxScheme else "base"
        val cnbBase = "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/v1.0.0"
        val cnbModel = "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/model"
        val ghBase = "https://github.com/amzxyz/rime_wanxiang/releases/download/dict-nightly"
        val ghModel = "https://github.com/amzxyz/RIME-LMDG/releases/download/LTS"

        val schemaUrl = if (downloadSource == "CNB") "$cnbBase/rime-wanxiang-$schemeStr${if(isPro) "-fuzhu" else ""}.zip" else "$ghBase/rime-wanxiang-$schemeStr${if(isPro) "-fuzhu" else ""}.zip"
        val dictUrl = if (downloadSource == "CNB") "$cnbBase/${if(isPro) "pro-$schemeStr-fuzhu" else "base"}-dicts.zip" else "$ghBase/${if(isPro) "pro-$schemeStr-fuzhu" else "base"}-dicts.zip"
        val modelUrl = if (downloadSource == "CNB") "$cnbModel/wanxiang-lts-zh-hans.gram" else "$ghModel/wanxiang-lts-zh-hans.gram"

        val tasksMap = listOf(
            "🚀 全量更新 (推荐)" to listOf(schemaUrl, dictUrl, modelUrl),
            "⚙️ 仅方案组件" to listOf(schemaUrl),
            "🕮 仅词库组件" to listOf(dictUrl),
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
        tasksMap.forEach { (name, urls) ->
            Button(
                onClick = {
                    if (!isDownloading) {
                        coroutineScope.launch {
                            isDownloading = true
                            activeTasks = urls.map { url -> 
                                val fName = url.substringAfterLast("/")
                                val title = when {
                                    fName.contains("dicts") -> "词库包 ($fName)"
                                    fName.contains("gram") -> "语法模型 ($fName)"
                                    else -> "主方案 ($fName)"
                                }
                                TaskState(title, url) 
                            }
                            
                            for (task in activeTasks) {
                                downloadAndDeployTask(task, githubToken)
                                if (task.isError) break 
                            }
                            isDownloading = false
                        }
                    }
                },
                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp).height(48.dp),
                enabled = !isDownloading,
                colors = ButtonDefaults.buttonColors(containerColor = MorandiGreen),
                shape = RoundedCornerShape(8.dp)
            ) {
                Text(name, fontSize = 15.sp, fontWeight = FontWeight.Bold)
            }
        }
        Spacer(modifier = Modifier.height(30.dp))
    }
}

suspend fun downloadAndDeployTask(task: TaskState, token: String) {
    withContext(Dispatchers.IO) {
        val rimeDirs = listOf(
            File(Environment.getExternalStorageDirectory(), "rime"),
            File(Environment.getExternalStorageDirectory(), "Android/data/com.osfans.trime/files/rime")
        )
        val rimeDir = rimeDirs.firstOrNull { it.exists() } ?: rimeDirs[0]
        if (!rimeDir.exists()) rimeDir.mkdirs()

        val fileName = task.url.substringAfterLast("/")
        val tmpFile = File(rimeDir, "$fileName.tmp")
        
        val maxRetries = 3
        var success = false

        for (attempt in 1..maxRetries) {
            try {
                task.status = if (attempt > 1) "重试中($attempt/$maxRetries)..." else "连接中..."
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
                    throw Exception("HTTP码: $responseCode")
                }

                if (!isAppend && downloadedLen > 0) {
                    downloadedLen = 0L; tmpFile.delete()
                }

                val contentLength = connection.contentLength.toLong()
                val totalSize = if (contentLength < 0) -1L else if (isAppend) downloadedLen + contentLength else contentLength

                val input = connection.inputStream
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
                if (totalSize > 0 && tmpFile.length() < totalSize) throw Exception("文件不完整")
                success = true
                break
            } catch (e: Exception) {
                e.printStackTrace()
                delay(1500)
            }
        }

        if (!success) {
            withContext(Dispatchers.Main) { task.isError = true; task.status = "❌ 下载失败" }
            return@withContext
        }

        try {
            withContext(Dispatchers.Main) { task.status = "正在解压部署..."; task.progress = 1.0f }
            if (fileName.endsWith(".zip")) {
                val isDictZip = fileName.contains("dicts")
                val extractDir = File(rimeDir, "wanxiang_tmp_ext")
                if (extractDir.exists()) extractDir.deleteRecursively()
                extractDir.mkdirs()

                ZipInputStream(tmpFile.inputStream()).use { zis ->
                    var entry = zis.nextEntry
                    while (entry != null) {
                        val file = File(extractDir, entry.name)
                        if (entry.isDirectory) file.mkdirs()
                        else {
                            file.parentFile?.mkdirs()
                            FileOutputStream(file).use { fos -> zis.copyTo(fos) }
                        }
                        zis.closeEntry()
                        entry = zis.nextEntry
                    }
                }
                tmpFile.delete()

                fun copyContentsTo(srcDir: File, destDir: File) {
                    if (!destDir.exists()) destDir.mkdirs()
                    srcDir.listFiles()?.forEach { child -> child.copyRecursively(File(destDir, child.name), overwrite = true) }
                }

                if (isDictZip) {
                    var dictRoot = extractDir
                    extractDir.walkTopDown().forEach { file ->
                        if (file.name.endsWith(".dict.yaml")) { dictRoot = file.parentFile!!; return@forEach }
                    }
                    copyContentsTo(dictRoot, File(rimeDir, "dicts"))
                } else {
                    var schemaRoot = extractDir
                    extractDir.walkTopDown().forEach { file ->
                        if (file.name == "default.yaml" || file.name == "rime.lua") { schemaRoot = file.parentFile!!; return@forEach }
                    }
                    copyContentsTo(schemaRoot, rimeDir)
                }
                extractDir.deleteRecursively()
            } else {
                val finalFile = File(rimeDir, fileName)
                if (finalFile.exists()) finalFile.delete()
                tmpFile.renameTo(finalFile)
            }
            withContext(Dispatchers.Main) { task.isFinished = true; task.status = "✅ 部署完成" }
        } catch (e: Exception) {
            e.printStackTrace()
            withContext(Dispatchers.Main) { task.isError = true; task.status = "❌ 部署异常: ${e.message}" }
        }
    }
}
