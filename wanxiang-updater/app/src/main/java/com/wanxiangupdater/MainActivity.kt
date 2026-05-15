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

    // 🌟 记忆读取：尝试从小账本里拿，拿不到再用默认值
    var isPro by remember { mutableStateOf(sharedPref.getBoolean("is_pro", true)) }
    var auxScheme by remember { mutableStateOf(sharedPref.getString("aux_scheme", "zrm") ?: "zrm") }
    var downloadSource by remember { mutableStateOf(sharedPref.getString("download_source", "CNB") ?: "CNB") }
    var updateChannel by remember { mutableStateOf(sharedPref.getString("update_channel", "Stable") ?: "Stable") }
    
    // GitHub Token 记忆
    var githubToken by remember { 
        mutableStateOf(sharedPref.getString("gh_token", "") ?: "") 
    }
    var excludeRulesText by remember { 
        mutableStateOf(sharedPref.getString("exclude_rules", DEFAULT_EXCLUDE_RULES) ?: DEFAULT_EXCLUDE_RULES) 
    }
    var showAdvancedRules by remember { mutableStateOf(false) }

    // 路径记忆 (全局授权池)
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

    // 版本云端探测雷达
    var latestStableTag by remember { mutableStateOf("v1.0.0") }
    var cloudVersionName by remember { mutableStateOf("") }
    var updaterDownloadUrl by remember { mutableStateOf("") }
    var isCheckingUpdate by remember { mutableStateOf(true) }

    LaunchedEffect(Unit) {
        withContext(Dispatchers.IO) {
            // 1. 探测主方案 Tag
            try {
                val url = URL("https://api.github.com/repos/amzxyz/rime-wanxiang/releases/latest")
                val conn = url.openConnection() as HttpURLConnection
                conn.setRequestProperty("User-Agent", "WanxiangUpdater-Agent")
                if (githubToken.isNotBlank()) {
                    conn.setRequestProperty("Authorization", "Bearer $githubToken")
                }
                conn.connectTimeout = 10000
                conn.connect()
                if (conn.responseCode == 200) {
                    val content = conn.inputStream.bufferedReader().readText()
                    Regex("\"tag_name\"\\s*:\\s*\"([^\"]+)\"").find(content)?.groupValues?.get(1)?.let { 
                        latestStableTag = it 
                    }
                }
            } catch (e: Exception) { 
                e.printStackTrace() 
            }

            // 2. 探测更新器自身
            try {
                val toolUrl = URL("https://api.github.com/repos/amzxyz/RIME-LMDG/releases/tags/tool")
                val toolConn = toolUrl.openConnection() as HttpURLConnection
                toolConn.setRequestProperty("User-Agent", "WanxiangUpdater-Agent")
                if (githubToken.isNotBlank()) {
                    toolConn.setRequestProperty("Authorization", "Bearer $githubToken")
                }
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
                        // 精准前缀正则提取
                        if (name.startsWith("Wanxiang-Updater-Android") && name.endsWith(".apk")) {
                            updaterDownloadUrl = asset.getString("browser_download_url")
                            val versionMatch = Regex("""Wanxiang-Updater-Android.*?(\d+\.\d+(\.\d+)?)""").find(name)
                            cloudVersionName = versionMatch?.groupValues?.get(1) ?: ""
                            break
                        }
                    }
                }
            } catch (e: Exception) { 
                e.printStackTrace() 
            }
            isCheckingUpdate = false
        }
    }

    var isDownloading by remember { mutableStateOf(false) }
    var activeTasks by remember { mutableStateOf<List<TaskState>>(emptyList()) }
    val coroutineScope = rememberCoroutineScope()

    val auxMap = mapOf("zrm" to "自然码", "wx" to "万象", "flypy" to "小鹤", "moqi" to "墨奇", "hanxin" to "汉心", "shouyou" to "首右", "shyplus" to "首右+", "tiger" to "虎码", "wubi" to "五笔")

    // --- 新增：Tab状态与自定义任务状态 ---
    var selectedTabIndex by remember { mutableStateOf(0) }
    var customTasks by remember { mutableStateOf(loadCustomTasks(sharedPref.getString("custom_tasks_data", "[]") ?: "[]")) }

    Column(modifier = Modifier.fillMaxSize()) {
        // 🌟 物理隔离墙：顶层标签页
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
            // 原有的主界面内容
            Column(modifier = Modifier.padding(16.dp).verticalScroll(rememberScrollState()).weight(1f)) {
                Text("📱 万象拼音更新器", fontSize = 24.sp, fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
                Text("v$localVersionName • 全功能终极版", fontSize = 12.sp, color = Color.Gray)
                Spacer(modifier = Modifier.height(16.dp))

                // UI：版本对狙卡片
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
                            onClick = { 
                                if (updaterDownloadUrl.isNotBlank()) {
                                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(updaterDownloadUrl))) 
                                }
                            },
                            enabled = hasNewVersion,
                            colors = ButtonDefaults.buttonColors(containerColor = if (hasNewVersion) MorandiGreen else Color.LightGray),
                            modifier = Modifier.height(32.dp),
                            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 0.dp)
                        ) {
                            Text(if (hasNewVersion) "立即更新" else "无需操作", fontSize = 12.sp, fontWeight = FontWeight.Bold)
                        }
                    }
                }

                // 目标路径卡片
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
                                        val newPaths = savedPaths - pathStr
                                        savedPaths = newPaths
                                        sharedPref.edit().putStringSet("deploy_paths", newPaths.toSet()).apply()
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
                                        savedPaths = savedPaths + "DEFAULT"
                                        sharedPref.edit().putStringSet("deploy_paths", savedPaths.toSet()).apply()
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

                // 方案与通道选择
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
                            FlowRow(modifier = Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                auxMap.forEach { (key, name) ->
                                    FilterChip(
                                        selected = (auxScheme == key), 
                                        onClick = { 
                                            auxScheme = key 
                                            sharedPref.edit().putString("aux_scheme", key).apply() // 🌟 存入选择的辅助码
                                        }, 
                                        label = { Text(name, fontSize = 12.sp) }
                                    )
                                }
                            }
                        }
                    }
                }
                Spacer(modifier = Modifier.height(12.dp))

                // 高级规则卡片
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

                // 下载源及 Token 配置
                Card(colors = CardDefaults.cardColors(containerColor = Color.White), border = CardDefaults.outlinedCardBorder(true), modifier = Modifier.fillMaxWidth()) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text("🌐 下载源配置", fontWeight = FontWeight.Bold, color = Color.DarkGray)
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(selected = downloadSource == "CNB", onClick = { downloadSource = "CNB"; sharedPref.edit().putString("download_source", "CNB").apply() })
                            Text("CNB", fontSize = 14.sp)
                            Spacer(modifier = Modifier.width(8.dp))
                            RadioButton(selected = downloadSource == "GitHub", onClick = { downloadSource = "GitHub"; sharedPref.edit().putString("download_source", "GitHub").apply() })
                            Text("GitHub", fontSize = 14.sp)
                        }
                        
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

                // 核心下载逻辑变量生成
                val schemeStr = if (isPro) auxScheme else "base"
                val activeTag = if (downloadSource == "CNB") (if (updateChannel == "Stable") latestStableTag else "v1.0.0") else (if (updateChannel == "Stable") latestStableTag else "dict-nightly")
                val baseDownloadUrl = if (downloadSource == "CNB") "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/$activeTag" else "https://github.com/amzxyz/rime-wanxiang/releases/download/$activeTag"
                val dictTag = if (downloadSource == "CNB") "v1.0.0" else "dict-nightly"
                val dictBaseUrl = if (downloadSource == "CNB") "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/$dictTag" else "https://github.com/amzxyz/rime-wanxiang/releases/download/$dictTag"
                
                val schemaUrl = "$baseDownloadUrl/rime-wanxiang-$schemeStr${if(isPro) "-fuzhu" else ""}.zip"
                val dictUrl = "$dictBaseUrl/${if(isPro) "pro-$schemeStr-fuzhu" else "base"}-dicts.zip"
                val modelUrl = if (downloadSource == "CNB") "https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/model/wanxiang-lts-zh-hans.gram" else "https://github.com/amzxyz/RIME-LMDG/releases/download/LTS/wanxiang-lts-zh-hans.gram"
                
                val tasksMap = listOf(
                    "🚀 全量更新" to listOf(schemaUrl, dictUrl, modelUrl), 
                    "⚙️ 仅方案" to listOf(schemaUrl), 
                    "📖 仅词库" to listOf(dictUrl), 
                    "🧠 仅模型" to listOf(modelUrl)
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
                                    if (savedPaths.isEmpty()) return@Button 
                                    
                                    // 🌟 强力拦截：如果包含了默认路径，且没给所有文件权限，直接弹窗拦截！
                                    if (savedPaths.contains("DEFAULT") && Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && !Environment.isExternalStorageManager()) {
                                        showPermissionDialog = true
                                        return@Button
                                    }

                                    val currentRules = excludeRulesText.lines().filter { it.isNotBlank() }
                                    executeTasks(urls, coroutineScope, { isDownloading = it }, { activeTasks = it }, githubToken, savedPaths, context, currentRules) 
                                },
                                modifier = Modifier.weight(1f).height(48.dp),
                                enabled = !isDownloading && savedPaths.isNotEmpty(),
                                shape = RoundedCornerShape(8.dp)
                            ) { 
                                Text(name, fontSize = 13.sp, fontWeight = FontWeight.Bold) 
                            }
                        }
                    }
                }
            }
        } else {
            // 自定义模式 UI
            CustomModeTab(
                customTasks = customTasks,
                savedPaths = savedPaths,
                onTasksChange = { newTasks ->
                    customTasks = newTasks
                    saveCustomTasks(newTasks, sharedPref)
                },
                // 🌟 新增：在这里接收自定义页面新授权的目录，并同步给底座
                onNewPathAuthorized = { newPath ->
                    val newPaths = (savedPaths + newPath).distinct()
                    savedPaths = newPaths
                    sharedPref.edit().putStringSet("deploy_paths", newPaths.toSet()).apply()
                },
                coroutineScope = coroutineScope,
                setDownloading = { isDownloading = it },
                setTasks = { activeTasks = it },
                context = context,
                activeTasks = activeTasks
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
    onNewPathAuthorized: (String) -> Unit,
    coroutineScope: kotlinx.coroutines.CoroutineScope,
    setDownloading: (Boolean) -> Unit,
    setTasks: (List<TaskState>) -> Unit,
    context: Context,
    activeTasks: List<TaskState>
) {
    var taskAwaitingPath by remember { mutableStateOf<String?>(null) }
    var isDownloading by remember { mutableStateOf(activeTasks.isNotEmpty()) }

    LaunchedEffect(activeTasks) {
        isDownloading = activeTasks.isNotEmpty() && !activeTasks.all { it.isFinished || it.isError }
    }

    val customDirLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            context.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
            val pathStr = uri.toString()
            onNewPathAuthorized(pathStr)
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
                                        targets.zip(uiTasks).forEach { (taskData, uiState) ->
                                            downloadAndDeployTask(uiState, "", listOf(taskData.boundPath), context, emptyList())
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
                            
                            // 🌟 1. 任务别名：标签浮在上面，框压低到 38dp
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
                            
                            // 🌟 2. 下载链接：标签浮在上面，框压低到 38dp
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

                            // 🌟 3. 解压路径与配置按钮
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
                                    onClick = { if (task.url.isNotBlank() && task.boundPath.isNotBlank()) executeTasks(listOf(task.url), coroutineScope, setDownloading, setTasks, "", listOf(task.boundPath), context, emptyList()) },
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
    rules: List<String>
) {
    scope.launch {
        setDownloading(true)
        val activeTasks = urls.map { url -> 
            val fName = url.substringAfterLast("/")
            val title = if (fName.contains("dicts")) "词库包" else if (fName.contains("gram")) "模型" else "方案"
            TaskState("$title ($fName)", url) 
        }
        setTasks(activeTasks)
        for (task in activeTasks) {
            downloadAndDeployTask(task, token, targetPaths, context, rules)
            if (task.isError) break 
        }
        setDownloading(false)
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
        val stagingDir = File(context.cacheDir, "wanxiang_staging")
        if (!stagingDir.exists()) {
            stagingDir.mkdirs()
        }
        val tmpFile = File(stagingDir, "${task.url.substringAfterLast("/")}.tmp")
        var success = false
        var lastErrorMsg = ""

        // 判断是不是本地路径 (以 / 或 file:// 或 content:// 开头)
        val isLocalFile = task.url.startsWith("/") || task.url.startsWith("file://") || task.url.startsWith("content://")

        if (isLocalFile) {

            try {
                withContext(Dispatchers.Main) { 
                    task.status = "读取本地文件..." 
                    task.progress = -1f // 无限流动动画
                }
                
                // 兼容普通路径和 content URI
                val uri = if (task.url.startsWith("/")) Uri.fromFile(File(task.url)) else Uri.parse(task.url)
                
                // 利用 ContentResolver 流式复制到沙盒中，完美兼容安卓各种玄学权限
                context.contentResolver.openInputStream(uri)?.use { input ->
                    FileOutputStream(tmpFile).use { output ->
                        input.copyTo(output)
                    }
                } ?: throw Exception("找不到文件或无权限读取该本地路径")
                
                success = true
                withContext(Dispatchers.Main) { 
                    task.progress = 1f
                    task.status = "本地读取完成" 
                }
            } catch (e: Exception) {
                lastErrorMsg = e.message ?: "本地文件读取异常"
            }
        } else {
            for (attempt in 1..3) {
                try {
                    withContext(Dispatchers.Main) { 
                        task.status = if (attempt > 1) "重试中($attempt/3)" else "连接中..." 
                    }
                    val url = URL(task.url)
                    
                    // 1. 发送 HEAD 请求，就像浏览器一样先探测文件有多大
                    var totalSize = 0L
                    val sizeConn = url.openConnection() as HttpURLConnection
                    sizeConn.setRequestProperty("User-Agent", "WanxiangUpdater-Agent")
                    if (task.url.contains("github.com") && token.isNotBlank()) {
                        sizeConn.setRequestProperty("Authorization", "Bearer $token")
                    }
                    sizeConn.requestMethod = "HEAD" 
                    totalSize = sizeConn.contentLength.toLong()
                    sizeConn.disconnect()

                    if (totalSize > 0) {
                        val threadCount = 3
                        val chunkSize = totalSize / threadCount
                        val downloadedLen = java.util.concurrent.atomic.AtomicLong(0)
                        var lastUpdateTime = System.currentTimeMillis()

                        kotlinx.coroutines.coroutineScope {
                            // 开启 3 个并发协程
                            val deferreds = (0 until threadCount).map { i ->
                                kotlinx.coroutines.async(Dispatchers.IO) {
                                    val start = i * chunkSize
                                    val end = if (i == threadCount - 1) totalSize - 1 else (start + chunkSize - 1)
                                    
                                    val partConn = URL(task.url).openConnection() as HttpURLConnection
                                    partConn.setRequestProperty("User-Agent", "WanxiangUpdater-Agent")
                                    if (task.url.contains("github.com") && token.isNotBlank()) {
                                        partConn.setRequestProperty("Authorization", "Bearer $token")
                                    }
                                    partConn.setRequestProperty("Range", "bytes=$start-$end")
                                    partConn.connectTimeout = 10000
                                    partConn.readTimeout = 10000
                                    
                                    val partFile = File(stagingDir, "${tmpFile.name}.part$i")
                                    partConn.inputStream.buffered().use { input ->
                                        FileOutputStream(partFile).buffered().use { output ->
                                            val data = ByteArray(65536)
                                            var count: Int
                                            while (input.read(data).also { count = it } != -1) {
                                                output.write(data, 0, count)
                                                val currentDownloaded = downloadedLen.addAndGet(count.toLong())
                                                val currentTime = System.currentTimeMillis()
                                                if (currentTime - lastUpdateTime > 150) {
                                                    lastUpdateTime = currentTime
                                                    withContext(Dispatchers.Main) {
                                                        task.progress = currentDownloaded.toFloat() / totalSize
                                                        task.status = "${String.format("%.1f", currentDownloaded/1024.0/1024.0)}MB (多线程)"
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                            deferreds.awaitAll()
                        }
                        withContext(Dispatchers.Main) { task.status = "文件拼装中..." }
                        FileOutputStream(tmpFile).buffered().use { output ->
                            for (i in 0 until threadCount) {
                                val partFile = File(stagingDir, "${tmpFile.name}.part$i")
                                partFile.inputStream().buffered().use { it.copyTo(output) }
                                partFile.delete() // 阅后即焚，不留垃圾
                            }
                        }
                        withContext(Dispatchers.Main) { task.progress = 1f }

                    } else {
                        val conn = url.openConnection() as HttpURLConnection
                        conn.setRequestProperty("User-Agent", "WanxiangUpdater-Agent")
                        if (task.url.contains("github.com") && token.isNotBlank()) {
                            conn.setRequestProperty("Authorization", "Bearer $token")
                        }
                        conn.inputStream.buffered().use { input ->
                            FileOutputStream(tmpFile).buffered().use { output ->
                                val data = ByteArray(131072)
                                var count: Int
                                var downloaded = 0L
                                var lastUpdateTime = System.currentTimeMillis()
                                while (input.read(data).also { count = it } != -1) {
                                    downloaded += count
                                    output.write(data, 0, count)
                                    val currentTime = System.currentTimeMillis()
                                    if (currentTime - lastUpdateTime > 150) {
                                        lastUpdateTime = currentTime
                                        withContext(Dispatchers.Main) { task.status = "${String.format("%.1f", downloaded/1024.0/1024.0)}MB (单线)" }
                                    }
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
        }

        if (success) {
            try {
                withContext(Dispatchers.Main) { 
                    task.status = "解压中..." 
                    task.progress = -1f 
                }
                val extractDir = File(stagingDir, "extracted_${System.currentTimeMillis()}")
                extractDir.mkdirs()
                
                if (task.url.endsWith(".zip")) {
                    ZipInputStream(tmpFile.inputStream()).use { zis ->
                        var entry = zis.nextEntry
                        while (entry != null) {
                            val f = File(extractDir, entry.name)
                            if (entry.isDirectory) {
                                f.mkdirs()
                            } else { 
                                f.parentFile?.mkdirs()
                                FileOutputStream(f).use { zis.copyTo(it) } 
                            }
                            entry = zis.nextEntry
                        }
                    }
                } else {
                    tmpFile.copyTo(File(extractDir, task.url.substringAfterLast("/")))
                }

                var realSrcDir = extractDir
                val subFiles = extractDir.listFiles()
                if (subFiles != null && subFiles.size == 1 && subFiles[0].isDirectory) {
                    realSrcDir = subFiles[0] 
                }

                val excludeRegexList = rules.mapNotNull { 
                    try { Regex(it) } catch (e: Exception) { null } 
                }
                val isDict = task.url.contains("dicts")

                var successCount = 0
                val errorList = mutableListOf<String>()

                for ((index, pathStr) in targetPaths.withIndex()) {
                    try {
                        if (index > 0) delay(500) 
                        withContext(Dispatchers.Main) { task.status = "解压目标 ${index + 1}/${targetPaths.size}..." }
                        
                        if (pathStr == "DEFAULT") {
                            val target = if (isDict) File(Environment.getExternalStorageDirectory(), "rime/dicts") else File(Environment.getExternalStorageDirectory(), "rime")
                            copyNormal(realSrcDir, target, excludeRegexList)
                        } else {
                            val rootDoc = DocumentFile.fromTreeUri(context, Uri.parse(pathStr))
                            if (rootDoc != null) {
                                var targetDoc = rootDoc
                                if (isDict) {
                                    var dictsDoc = rootDoc.findFile("dicts")
                                    if (dictsDoc == null) {
                                        dictsDoc = rootDoc.createDirectory("dicts")
                                        if (dictsDoc == null) dictsDoc = rootDoc.findFile("dicts") 
                                    }
                                    if (dictsDoc != null) targetDoc = dictsDoc else throw Exception("SAF底层拒绝访问")
                                }
                                copySaf(context, realSrcDir, targetDoc, excludeRegexList)
                            } else {
                                throw Exception("授权目录已失效")
                            }
                        }
                        successCount++
                    } catch (e: Exception) {
                        e.printStackTrace()
                        val pathName = if (pathStr == "DEFAULT") "默认" else "授权${index + 1}"
                        errorList.add("$pathName(${e.message ?: e.javaClass.simpleName})")
                    }
                }

                withContext(Dispatchers.Main) { 
                    if (successCount == targetPaths.size) {
                        task.isFinished = true
                        task.progress = 1f
                        task.status = "✅ 解压完成"
                    } else if (successCount > 0) {
                        task.isFinished = true 
                        task.progress = 1f 
                        task.status = "⚠️ 部分完成 [失败: ${errorList.joinToString()}]"
                    } else {
                        task.isError = true
                        task.progress = 0f
                        task.status = "❌ 全部失败 [${errorList.joinToString()}]"
                    }
                }
            } catch (e: Exception) { 
                e.printStackTrace()
                withContext(Dispatchers.Main) { task.isError = true; task.progress = 0f; task.status = "❌ 解压或准备解压失败" } 
            }
        } else { 
            withContext(Dispatchers.Main) { task.isError = true; task.progress = 0f; task.status = "❌ 获取文件失败: $lastErrorMsg" } 
        }
        stagingDir.deleteRecursively()
    }
}

// 🌟 物理强杀版普通复制逻辑
fun copyNormal(src: File, dest: File, rules: List<Regex>, currentPath: String = "") {
    if (!dest.exists()) {
        dest.mkdirs()
    }
    src.listFiles()?.forEach { file ->
        val relPath = if (currentPath.isEmpty()) file.name else "$currentPath/${file.name}"
        val targetFile = File(dest, file.name)
        
        // 护盾检测
        if (rules.any { it.containsMatchIn(relPath) } && targetFile.exists()) {
            return@forEach
        }
        
        if (file.isDirectory) {
            copyNormal(file, targetFile, rules, relPath)
        } else {
            // 🔪 物理级强力斩杀：不管成不成功，先发个 delete 指令打碎系统文件锁
            if (targetFile.exists()) {
                targetFile.delete()
            }
            file.copyTo(targetFile, overwrite = true)
        }
    }
}

// 🌟 对抗安卓 SAF 幽灵缓存的完全体复制逻辑
fun copySaf(context: Context, src: File, dest: DocumentFile, rules: List<Regex>, currentPath: String = "") {
    src.listFiles()?.forEach { file ->
        val relPath = if (currentPath.isEmpty()) file.name else "$currentPath/${file.name}"
        
        // 护盾检测
        if (rules.any { it.containsMatchIn(relPath) } && dest.findFile(file.name) != null) {
            return@forEach
        }
        
        if (file.isDirectory) {
            // 👻 幽灵缓存对抗：找不到 -> 新建 -> 失败的话强行再找一次！
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
            // 🔪 暴力摧毁旧文件
            val existingFile = dest.findFile(file.name)
            if (existingFile != null && existingFile.exists()) {
                existingFile.delete() // 强力删除旧文件
            }
            
            // 👻 再次对抗幽灵缓存：如果新建文件返回空，说明缓存说没删干净，那就再把它找出来硬覆盖！
            var newDoc = dest.createFile("*/*", file.name)
            if (newDoc == null) newDoc = dest.findFile(file.name)
            
            if (newDoc != null) {
                // "wt" 模式：写入并截断清空（最强硬的覆写模式）
                context.contentResolver.openOutputStream(newDoc.uri, "wt")?.use { out -> 
                    file.inputStream().use { it.copyTo(out) } 
                } ?: throw Exception("文件流被占用拒绝写入:${file.name}")
            } else {
                throw Exception("文件冲突无法创建:${file.name}")
            }
        }
    }
}