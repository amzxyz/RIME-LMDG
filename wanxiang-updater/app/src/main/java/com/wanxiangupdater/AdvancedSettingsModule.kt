package com.wanxiangupdater

import android.content.Context
import android.net.Uri
import android.os.Environment
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.documentfile.provider.DocumentFile
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.Locale

private data class AdvancedFile(val group: String, val name: String, val label: String, val sections: List<Pair<String, String>>)
private data class AdvancedField(val path: String, val title: String, val desc: String, val type: String, val value: String, val options: List<String>)

private object AdvancedPythonBridge {
    private val lock = Any()
    private fun python(context: Context): Python {
        if (!Python.isStarted()) synchronized(lock) {
            if (!Python.isStarted()) Python.start(AndroidPlatform(context.applicationContext))
        }
        return Python.getInstance()
    }
    fun scan(context: Context, root: File): List<AdvancedFile> {
        val text = python(context).getModule("advanced_settings_mobile")
            .callAttr("scan_sections", root.absolutePath).toString()
        val rows = JSONArray(text)
        return (0 until rows.length()).map { i ->
            val row = rows.getJSONObject(i)
            val sections = row.optJSONArray("sections")?.let { a ->
                (0 until a.length()).map { j -> val s = a.getJSONObject(j); s.optString("key") to s.optString("title") }
            } ?: emptyList()
            AdvancedFile(row.optString("group"), row.optString("file"), row.optString("name"), sections)
        }
    }
    fun form(context: Context, root: File, file: String, section: String): List<AdvancedField> {
        val text = python(context).getModule("advanced_settings_mobile")
            .callAttr("load_form", root.absolutePath, file, section).toString()
        val fields = JSONArray(JSONObject(text).optString("fields", "[]"))
        return (0 until fields.length()).map { i ->
            val row = fields.getJSONObject(i)
            val options = row.optJSONArray("options")?.let { a -> (0 until a.length()).map { j -> a.optString(j) } } ?: emptyList()
            AdvancedField(row.optString("path"), row.optString("title"), row.optString("desc"), row.optString("type"), row.optString("value"), options)
        }
    }
    fun save(context: Context, root: File, file: String, section: String, direct: Boolean, values: Map<String, String>): String {
        val obj = JSONObject()
        values.forEach { (k, v) -> obj.put(k, v) }
        return python(context).getModule("advanced_settings_mobile")
            .callAttr("save_form", root.absolutePath, file, section, direct, obj.toString()).toString()
    }
}

private fun advancedRootFile(path: String): File = when {
    path == "DEFAULT" -> File(Environment.getExternalStorageDirectory(), "rime")
    isRootTarget(path) -> File(rootTargetPath(path))
    else -> File(path)
}

private fun copySafToStage(context: Context, root: DocumentFile, stage: File) {
    stage.mkdirs()
    root.listFiles().forEach { child ->
        val name = child.name ?: return@forEach
        val out = File(stage, name)
        if (child.isDirectory) copySafToStage(context, child, out)
        else if ((name.endsWith(".yaml", true) || name.endsWith(".yml", true)) && !name.endsWith(".dict.yaml", true)) {
            context.contentResolver.openInputStream(child.uri)?.use { input -> out.outputStream().use { input.copyTo(it) } }
        }
    }
}

private fun copyStageFileToSaf(context: Context, root: DocumentFile, file: File, relative: String = "") {
    if (!file.isFile) return
    val name = file.name
    val existing = root.findFile(name)
    val target = existing ?: root.createFile("text/yaml", name) ?: return
    context.contentResolver.openOutputStream(target.uri, "wt")?.use { out -> file.inputStream().use { it.copyTo(out) } }
}

private fun findSafRoot(context: Context, path: String): DocumentFile? =
    if (path == "DEFAULT" || isRootTarget(path)) null else DocumentFile.fromTreeUri(context, Uri.parse(path))

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AdvancedSettingsScreen(
    context: Context,
    targetPath: String,
    onTargetPathChange: (String) -> Unit,
    onPickSafDirectory: () -> Unit
) {
    val scope = rememberCoroutineScope()
    var files by remember { mutableStateOf<List<AdvancedFile>>(emptyList()) }
    var selectedFile by remember { mutableStateOf<AdvancedFile?>(null) }
    var selectedSection by remember { mutableStateOf("") }
    var fields by remember { mutableStateOf<List<AdvancedField>>(emptyList()) }
    var values by remember { mutableStateOf<Map<String, String>>(emptyMap()) }
    var directMode by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf("请选择高级设置目录") }
    var busy by remember { mutableStateOf(false) }

    fun stageRoot(): Pair<File, DocumentFile?> {
        val saf = findSafRoot(context, targetPath)
        if (saf == null) return advancedRootFile(targetPath) to null
        val stage = File(context.cacheDir, "wanxiang_advanced_stage").apply { deleteRecursively(); mkdirs() }
        copySafToStage(context, saf, stage)
        return stage to saf
    }
    fun scan() {
        scope.launch {
            busy = true
            runCatching { withContext(Dispatchers.IO) { stageRoot().first.let { AdvancedPythonBridge.scan(context, it) } } }
                .onSuccess { files = it; selectedFile = it.firstOrNull(); selectedSection = it.firstOrNull()?.sections?.firstOrNull()?.first ?: ""; message = "已加载 ${it.size} 个受控配置文件" }
                .onFailure { files = emptyList(); message = "❌ 扫描失败：${it.message}" }
            busy = false
        }
    }
    fun loadForm(file: AdvancedFile, section: String) {
        scope.launch {
            busy = true
            runCatching { withContext(Dispatchers.IO) { stageRoot().first.let { AdvancedPythonBridge.form(context, it, file.name, section) } } }
                .onSuccess { fields = it; values = it.associate { f -> f.path to f.value }; message = "${file.label} / ${it.size} 项" }
                .onFailure { fields = emptyList(); message = "❌ 读取失败：${it.message}" }
            busy = false
        }
    }
    LaunchedEffect(targetPath) { if (targetPath.isNotBlank()) scan() }
    LaunchedEffect(selectedFile, selectedSection, directMode) { selectedFile?.let { loadForm(it, selectedSection) } }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)) {
        Text("🛠️ 高级设置", fontSize = 24.sp, fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
        Text("按桌面工具的 FILE_INDEX_META / SCHEMA_META_CONFIG 加载受控字段；补丁模式写入 .custom.yaml，直写模式修改源方案。", fontSize = 12.sp, color = Color.Gray)
        Spacer(Modifier.height(10.dp))
        Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color.White), border = CardDefaults.outlinedCardBorder(true)) {
            Column(Modifier.padding(12.dp)) {
                Text("配置目录", fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
                Text(if (targetPath == "DEFAULT") "默认 /rime" else if (isRootTarget(targetPath)) "Root ${rootTargetPath(targetPath)}" else if (targetPath.isBlank()) "未选择" else "SAF 授权目录", fontSize = 12.sp, color = Color.Gray)
                Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton({ onTargetPathChange("DEFAULT") }, Modifier.weight(1f)) { Text("默认 /rime") }
                    OutlinedButton(onPickSafDirectory, Modifier.weight(1f)) { Text("选择 SAF") }
                }
                Row(Modifier.fillMaxWidth().padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(selected = !directMode, onClick = { directMode = false }, label = { Text("补丁模式") })
                    FilterChip(selected = directMode, onClick = { directMode = true }, label = { Text("直写模式") })
                    Button({ scan() }, enabled = !busy, modifier = Modifier.weight(1f), colors = ButtonDefaults.buttonColors(containerColor = MorandiGreen)) { Text(if (busy) "处理中…" else "扫描") }
                }
            }
        }
        Spacer(Modifier.height(8.dp)); Text(message, fontSize = 12.sp, color = Color.Gray)
        files.forEach { file ->
            Card(Modifier.fillMaxWidth().padding(top = 8.dp), colors = CardDefaults.cardColors(containerColor = Color.White), border = CardDefaults.outlinedCardBorder(true)) {
                Column(Modifier.padding(10.dp)) {
                    TextButton({ selectedFile = file; selectedSection = file.sections.firstOrNull()?.first ?: "" }, Modifier.fillMaxWidth()) { Text("${if (selectedFile?.name == file.name) "●" else "○"} ${file.label}", modifier = Modifier.fillMaxWidth(), color = MorandiDarkGreen) }
                    if (selectedFile?.name == file.name) file.sections.forEach { (key, title) ->
                        FilterChip(selected = selectedSection == key, onClick = { selectedSection = key }, label = { Text(title, fontSize = 11.sp) }, modifier = Modifier.padding(end = 4.dp))
                    }
                }
            }
        }
        if (fields.isNotEmpty()) {
            Spacer(Modifier.height(10.dp))
            fields.forEach { field ->
                val current = values[field.path] ?: ""
                if (field.type == "bool") {
                    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                        Column(Modifier.weight(1f)) { Text(field.title, fontWeight = FontWeight.Bold); if (field.desc.isNotBlank()) Text(field.desc, fontSize = 11.sp, color = Color.Gray) }
                        Switch(checked = current.equals("true", true), onCheckedChange = { v -> values = values + (field.path to v.toString()) })
                    }
                } else if (field.type == "select" && field.options.isNotEmpty()) {
                    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                        Text(field.title, fontWeight = FontWeight.Bold)
                        if (field.desc.isNotBlank()) Text(field.desc, fontSize = 11.sp, color = Color.Gray)
                        Row(Modifier.fillMaxWidth().padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            field.options.forEach { option ->
                                FilterChip(selected = current == option, onClick = { values = values + (field.path to option) }, label = { Text(option, fontSize = 11.sp) })
                            }
                        }
                    }
                } else {
                    OutlinedTextField(value = current, onValueChange = { values = values + (field.path to it) }, label = { Text(field.title) }, supportingText = { if (field.desc.isNotBlank()) Text(field.desc) }, modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp), minLines = if (field.type in listOf("multiline_str", "list_text", "dynamic_list", "algebra_patch", "raw_yaml", "dynamic_block_list", "dynamic_kv_list")) 3 else 1, singleLine = field.type !in listOf("multiline_str", "list_text", "dynamic_list", "algebra_patch", "raw_yaml", "dynamic_block_list", "dynamic_kv_list"), textStyle = LocalTextStyle.current.copy(fontSize = 13.sp))
                }
            }
            Button(onClick = {
                val file = selectedFile ?: return@Button
                scope.launch {
                    busy = true; message = "正在校验并保存…"
                    runCatching {
                        withContext(Dispatchers.IO) {
                            val (stage, saf) = stageRoot()
                            val result = AdvancedPythonBridge.save(context, stage, file.name, selectedSection, directMode, values)
                            if (saf != null) {
                                stage.listFiles().filter { it.isFile && it.name.endsWith(".yaml", true) }.forEach { copyStageFileToSaf(context, saf, it) }
                            }
                            result
                        }
                    }.onSuccess { result -> message = "✅ ${JSONObject(result).optString("message")}：${JSONArray(JSONObject(result).optString("changed", "[]")).join(", ")}" }
                     .onFailure { message = "❌ 保存失败：${it.message}" }
                    busy = false
                }
            }, enabled = !busy, modifier = Modifier.fillMaxWidth().padding(top = 8.dp), colors = ButtonDefaults.buttonColors(containerColor = MorandiGreen)) { Text("💾 保存修改") }
        }
    }
}
