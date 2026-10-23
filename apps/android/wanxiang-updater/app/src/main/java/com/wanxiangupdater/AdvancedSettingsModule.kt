package com.wanxiangupdater

import android.content.Context
import android.net.Uri
import android.os.Environment
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
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
import org.json.JSONTokener
import java.io.File
import java.util.Locale

data class AdvancedFile(val group: String, val name: String, val label: String, val sections: List<Pair<String, String>>)
data class AdvancedChoice(val id: String, val label: String, val checked: Boolean)
data class AdvancedField(
    val path: String,
    val title: String,
    val desc: String,
    val type: String,
    val value: String,
    val options: List<String> = emptyList(),
    val choices: List<AdvancedChoice> = emptyList(),
    val actionButton: String = "",
    val templateJson: String = "",
    val presetKeysJson: String = ""
)

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
    fun form(context: Context, root: File, file: String, section: String, directMode: Boolean): List<AdvancedField> {
        val text = python(context).getModule("advanced_settings_mobile")
            .callAttr("load_form", root.absolutePath, file, section, directMode).toString()
        val fields = JSONArray(JSONObject(text).optString("fields", "[]"))
        return (0 until fields.length()).map { i ->
            val row = fields.getJSONObject(i)
            val options = row.optJSONArray("options")?.let { a -> (0 until a.length()).map { j -> a.optString(j) } } ?: emptyList()
            val choices = row.optJSONArray("choices")?.let { a ->
                (0 until a.length()).map { j ->
                    val c = a.getJSONObject(j)
                    AdvancedChoice(c.optString("id"), c.optString("label"), c.optBoolean("checked", false))
                }
            } ?: emptyList()
            AdvancedField(row.optString("path"), row.optString("title"), row.optString("desc"), row.optString("type"), row.optString("value"), options, choices, row.optString("actionButton"), row.optString("template"), row.optString("presetKeys"))
        }
    }
    fun save(context: Context, root: File, file: String, section: String, direct: Boolean, values: Map<String, String>): String {
        val obj = JSONObject()
        values.forEach { (k, v) -> obj.put(k, v) }
        return python(context).getModule("advanced_settings_mobile")
            .callAttr("save_form", root.absolutePath, file, section, direct, obj.toString()).toString()
    }
    fun common(context: Context, root: File, directMode: Boolean): List<AdvancedField> {
        val text = python(context).getModule("advanced_settings_mobile")
            .callAttr("load_common_settings", root.absolutePath, directMode).toString()
        return parseFields(text)
    }
    fun saveCommon(context: Context, root: File, direct: Boolean, values: Map<String, String>): String {
        val obj = JSONObject()
        values.forEach { (k, v) -> obj.put(k, v) }
        return python(context).getModule("advanced_settings_mobile")
            .callAttr("save_common_settings", root.absolutePath, direct, obj.toString()).toString()
    }
    fun importSwitches(context: Context, root: File): String {
        return python(context).getModule("advanced_settings_mobile")
            .callAttr("import_switches", root.absolutePath).toString()
    }
    private fun parseFields(text: String): List<AdvancedField> {
        val fields = JSONArray(JSONObject(text).optString("fields", "[]"))
        return (0 until fields.length()).map { i ->
            val row = fields.getJSONObject(i)
            val options = row.optJSONArray("options")?.let { a -> (0 until a.length()).map { j -> a.optString(j) } } ?: emptyList()
            val choices = row.optJSONArray("choices")?.let { a ->
                (0 until a.length()).map { j ->
                    val c = a.getJSONObject(j)
                    AdvancedChoice(c.optString("id"), c.optString("label"), c.optBoolean("checked", false))
                }
            } ?: emptyList()
            AdvancedField(row.optString("path"), row.optString("title"), row.optString("desc"), row.optString("type"), row.optString("value"), options, choices, row.optString("actionButton"), row.optString("template"), row.optString("presetKeys"))
        }
    }
}

private fun advancedRootFile(path: String): File = when {
    path == "DEFAULT" -> File(Environment.getExternalStorageDirectory(), "rime")
    isRootTarget(path) -> File(rootTargetPath(path))
    else -> File(path)
}

private fun copySafToStage(context: Context, root: DocumentFile, stage: File, dictionaryNames: Set<String> = emptySet()) {
    stage.mkdirs()
    root.listFiles().forEach { child ->
        val name = child.name ?: return@forEach
        val out = File(stage, name)
        if (child.isDirectory) copySafToStage(context, child, out, dictionaryNames)
        else if ((name.endsWith(".yaml", true) || name.endsWith(".yml", true)) &&
            (!name.endsWith(".dict.yaml", true) || name in dictionaryNames)) {
            context.contentResolver.openInputStream(child.uri)?.use { input -> out.outputStream().use { input.copyTo(it) } }
        }
    }
}

private fun copyStageFileToSaf(context: Context, root: DocumentFile, file: File, relative: String = "") {
    if (!file.isFile) return
    val name = file.name
    val existing = root.findFile(name)
    val target = existing ?: root.createFile("text/yaml", name)
        ?: throw java.io.IOException("无法在 SAF 目录创建文件：$name")
    val output = context.contentResolver.openOutputStream(target.uri, "wt")
        ?: throw java.io.IOException("无法写入 SAF 文件：$name")
    output.use { out -> file.inputStream().use { it.copyTo(out) } }
}

/** SAF is not atomic. Snapshot only the committed file set and restore best-effort on failure. */
private fun syncAdvancedStageToSaf(context: Context, saf: DocumentFile, stage: File, changed: JSONArray) {
    val names = (0 until changed.length()).map { changed.getString(it) }.distinct()
    require(names.all { it.isNotEmpty() && !it.contains('/') && !it.contains('\\') && it != "." && it != ".." }) {
        "保存结果包含非法文件名"
    }
    val backups = File(stage, "_advanced_saf_rollback").apply { mkdirs() }
    val existed = mutableSetOf<String>()
    var backupsReady = false
    try {
        // All backups must succeed before any destination is modified.
        names.forEach { name ->
            val existing = saf.findFile(name)
            if (existing != null) {
                require(existing.isFile) { "SAF 路径不是文件：$name" }
                existed.add(name)
                val backup = File(backups, name)
                val input = context.contentResolver.openInputStream(existing.uri)
                    ?: throw java.io.IOException("无法备份 SAF 文件：$name")
                input.use { stream -> backup.outputStream().use { stream.copyTo(it) } }
            }
        }
        backupsReady = true
        names.forEach { name ->
            val file = File(stage, name)
            if (file.isFile) copyStageFileToSaf(context, saf, file)
            else {
                val existing = saf.findFile(name)
                if (existing != null && !existing.delete()) throw java.io.IOException("无法删除 SAF 补丁：$name")
            }
        }
    } catch (original: Exception) {
        val failures = mutableListOf<String>()
        // Include the current item: an output stream can fail mid-file.
        if (backupsReady) names.forEach { name ->
            try {
                val old = saf.findFile(name)
                if (name in existed) {
                    copyStageFileToSaf(context, saf, File(backups, name))
                } else if (old != null && !old.delete()) {
                    throw java.io.IOException("回滚时无法删除 $name")
                }
                Unit
            } catch (rollback: Exception) { failures.add("$name: ${rollback.message}") }
        }
        if (failures.isNotEmpty()) throw java.io.IOException(
            "SAF 写入失败且部分回滚失败：${original.message}；${failures.joinToString()}。请重新选择目录核对文件", original
        )
        throw java.io.IOException(
            if (backupsReady) "SAF 写入失败，已恢复原始文件：${original.message}"
            else "SAF 备份失败，尚未修改原文件：${original.message}", original
        )
    } finally {
        backups.deleteRecursively()
    }
}

private fun findSafRoot(context: Context, path: String): DocumentFile? =
    if (path == "DEFAULT" || isRootTarget(path)) null else DocumentFile.fromTreeUri(context, Uri.parse(path))

private data class AdvancedCategory(
    val group: String,
    val key: String,
    val title: String,
    val files: List<AdvancedFile>
)

private fun schemeLayerLabel(file: AdvancedFile): String {
    return when (file.name.lowercase(Locale.ROOT)) {
        "default.yaml" -> "default"
        "wanxiang.schema.yaml" -> "Base"
        "wanxiang_pro.schema.yaml" -> "Pro"
        "wanxiang_lite.schema.yaml" -> "Lite"
        "wanxiang_t9.schema.yaml" -> "T9"
        "wanxiang_t9i.schema.yaml" -> "T9i"
        "wanxiang_english.schema.yaml" -> "English"
        "wanxiang_mixedcode.schema.yaml" -> "Mixedcode"
        "wanxiang_reverse.schema.yaml" -> "Reverse"
        "wanxiang_phrase.schema.yaml" -> "Phrase"
        "wanxiang_abbrev.schema.yaml" -> "Abbrev"
        "wanxiang_algebra.yaml" -> "Algebra"
        else -> file.name.substringBeforeLast(".yaml").substringAfterLast("/")
    }
}

private fun advancedGroupLabel(file: AdvancedFile): String =
    "${file.group}（${schemeLayerLabel(file)}）"

private fun buildAdvancedCategories(files: List<AdvancedFile>): Map<String, List<AdvancedCategory>> {
    // 每个实际 YAML 文件拥有自己的层级，避免 Base/Pro/Lite 或附属方案共用同一套保存入口。
    return files.groupBy { advancedGroupLabel(it) }.mapValues { (group, groupFiles) ->
        groupFiles
            .flatMap { file -> file.sections.map { section -> Triple(section.first, section.second, file) } }
            .groupBy { it.first to it.second }
            .map { (identity, entries) ->
                AdvancedCategory(
                    group = group,
                    key = identity.first,
                    title = identity.second,
                    files = entries.map { it.third }.distinctBy { it.name }
                )
            }
    }
}

/** Kept as JSON internally: this preserves nested mappings, numeric and boolean YAML types. */
private fun advancedArrayItems(value: String): List<String> {
    val raw = value.trim()
    if (raw.isEmpty()) return emptyList()
    return runCatching {
        val array = JSONArray(raw)
        (0 until array.length()).map { i ->
            val item = array.get(i)
            when (item) {
                is JSONObject -> item.toString(2)
                is JSONArray -> item.toString(2)
                else -> item.toString()
            }
        }
    }.getOrElse { value.lines().filter { it.isNotBlank() } }
}

private fun advancedJsonItem(value: String): Any {
    val raw = value.trim()
    if (raw.startsWith("{") || raw.startsWith("[")) {
        return runCatching { JSONTokener(raw).nextValue() }.getOrElse { value }
    }
    return value
}

private fun advancedMapItems(value: String): List<Pair<String, String>> {
    val raw = value.trim()
    if (raw.isEmpty()) return emptyList()
    return runCatching {
        val obj = JSONObject(raw)
        obj.keys().asSequence().map { k ->
            val v = obj.get(k)
            k to (if (v is JSONObject || v is JSONArray) v.toString() else v.toString())
        }.toList()
    }.getOrElse {
        value.lines().mapNotNull { line ->
            val ix = line.indexOf(':')
            if (ix > 0) line.substring(0, ix).trim() to line.substring(ix + 1).trim() else null
        }
    }
}

private fun advancedTypedScalar(text: String): Any {
    val t = text.trim()
    if (t == "true") return true
    if (t == "false") return false
    if (t == "null") return JSONObject.NULL
    if (t.matches(Regex("-?(0|[1-9][0-9]*)"))) return t.toLongOrNull() ?: text
    if (t.matches(Regex("-?(0|[1-9][0-9]*)\\.[0-9]+"))) return t.toDoubleOrNull() ?: text
    if (t.startsWith("[") || t.startsWith("{")) {
        return runCatching { JSONTokener(t).nextValue() }.getOrElse { text }
    }
    return text
}

@Composable
private fun AdvancedStructuredEditor(field: AdvancedField, value: String, onChange: (String) -> Unit) {
    val listKind = field.type in setOf("dynamic_list", "dynamic_block_list", "algebra_patch",
        "reverse_algebra", "english_algebra", "mixed_algebra", "list_text")
    val blockKind = field.type == "dynamic_block_list"
    val rowLabel = if (blockKind) "规则块" else "条目"
    Column(Modifier.fillMaxWidth().padding(vertical = 7.dp)) {
        Text(field.title, fontWeight = FontWeight.Bold)
        if (field.desc.isNotBlank()) Text(field.desc, fontSize = 11.sp, color = Color.Gray)
        if (listKind) {
            val items = advancedArrayItems(value)
            fun publish(next: List<String>) {
                val json = JSONArray()
                next.forEach { item -> json.put(advancedJsonItem(item)) }
                onChange(json.toString())
            }
            items.forEachIndexed { index, item ->
                Row(Modifier.fillMaxWidth().padding(top = 5.dp), verticalAlignment = Alignment.Top) {
                    OutlinedTextField(
                        value = item, onValueChange = { changed ->
                            publish(items.toMutableList().also { it[index] = changed })
                        }, label = { Text("$rowLabel ${index + 1}") },
                        minLines = if (blockKind) 3 else 1, maxLines = 8,
                        modifier = Modifier.weight(1f), textStyle = LocalTextStyle.current.copy(fontSize = 12.sp)
                    )
                    Column {
                        TextButton(onClick = {
                            if (index > 0) publish(items.toMutableList().also {
                                val item0 = it[index - 1]; it[index - 1] = it[index]; it[index] = item0
                            })
                        }, enabled = index > 0) { Text("↑") }
                        TextButton(onClick = {
                            if (index < items.lastIndex) publish(items.toMutableList().also {
                                val item0 = it[index + 1]; it[index + 1] = it[index]; it[index] = item0
                            })
                        }, enabled = index < items.lastIndex) { Text("↓") }
                        TextButton(onClick = { publish(items.filterIndexed { i, _ -> i != index }) }) { Text("删除", fontSize = 11.sp) }
                    }
                }
            }
            TextButton(onClick = {
                val initial = if (blockKind) {
                    runCatching {
                        val template = JSONObject(field.templateJson)
                        JSONObject().apply {
                            template.keys().forEach { k -> put(k, "") }
                        }.toString()
                    }.getOrDefault("{}")
                } else ""
                publish(items + initial)
            }) { Text("＋ 添加$rowLabel") }
            if (blockKind) Text("规则块内容使用 JSON 对象，可逐项添加、移动和删除。", fontSize = 10.sp, color = Color.Gray)
        } else {
            val entries = advancedMapItems(value)
            fun publish(next: List<Pair<String, String>>) {
                val keys = next.map { it.first }.filter { it.isNotBlank() }
                if (keys.distinct().size != keys.size) return // Duplicate keys would silently overwrite data.
                val json = JSONObject()
                next.forEach { (key, item) -> if (key.isNotBlank()) json.put(key, advancedTypedScalar(item)) }
                onChange(json.toString())
            }
            entries.forEachIndexed { index, entry ->
                Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.Top) {
                    OutlinedTextField(entry.first, onValueChange = { v ->
                        publish(entries.toMutableList().also { it[index] = v to entry.second })
                    }, label = { Text("键") }, modifier = Modifier.weight(0.8f), singleLine = true)
                    Spacer(Modifier.width(5.dp))
                    OutlinedTextField(entry.second, onValueChange = { v ->
                        publish(entries.toMutableList().also { it[index] = entry.first to v })
                    }, label = { Text("值（JSON 类型）") }, modifier = Modifier.weight(1.2f), maxLines = 5)
                    Column {
                        TextButton(onClick = { publish(entries.filterIndexed { i, _ -> i != index }) }) { Text("×") }
                        TextButton(onClick = {
                            if (index > 0) publish(entries.toMutableList().also {
                                val previous = it[index - 1]; it[index - 1] = it[index]; it[index] = previous
                            })
                        }, enabled = index > 0) { Text("↑") }
                        TextButton(onClick = {
                            if (index < entries.lastIndex) publish(entries.toMutableList().also {
                                val following = it[index + 1]; it[index + 1] = it[index]; it[index] = following
                            })
                        }, enabled = index < entries.lastIndex) { Text("↓") }
                    }
                }
            }
            TextButton(onClick = {
                val existing = entries.map { it.first }.toSet()
                val newKey = generateSequence(1) { it + 1 }
                    .map { if (it == 1) "new_key" else "new_key_$it" }
                    .first { it !in existing }
                publish(entries + (newKey to ""))
            }) { Text("＋ 添加键值") }
            val preset = runCatching { JSONObject(field.presetKeysJson) }.getOrNull()
            if (preset != null) {
                val keys = preset.keys().asSequence().filter { k -> entries.none { it.first == k } }.toList()
                if (keys.isNotEmpty()) {
                    Text("可添加的预设键", fontSize = 11.sp, color = Color.Gray)
                    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        keys.forEach { key ->
                            AssistChip(onClick = { publish(entries + (key to "")) }, label = { Text(key, fontSize = 10.sp) })
                        }
                    }
                }
            }
        }
    }
}

class AdvancedSettingsMemory {
    val files = mutableStateOf<List<AdvancedFile>>(emptyList())
    val selectedFile = mutableStateOf<AdvancedFile?>(null)
    val selectedSection = mutableStateOf("")
    val fields = mutableStateOf<List<AdvancedField>>(emptyList())
    val commonFields = mutableStateOf<List<AdvancedField>>(emptyList())
    val values = mutableStateOf<Map<String, String>>(emptyMap())
    val baselineValues = mutableStateOf<Map<String, String>>(emptyMap())
    val showCommon = mutableStateOf(true)
    val directMode = mutableStateOf(false)
    val message = mutableStateOf("请选择高级设置目录")
    val busy = mutableStateOf(false)
    val expandedGroups = mutableStateOf<Set<String>>(emptySet())
    val loadedTarget = mutableStateOf("")
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AdvancedSettingsScreen(
    context: Context,
    targetPath: String,
    state: AdvancedSettingsMemory,
    onTargetPathChange: (String) -> Unit,
    onPickSafDirectory: () -> Unit
) {
    val scope = rememberCoroutineScope()
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    var files by state.files
    var selectedFile by state.selectedFile
    var selectedSection by state.selectedSection
    var fields by state.fields
    var commonFields by state.commonFields
    var values by state.values
    var baselineValues by state.baselineValues
    var showCommon by state.showCommon
    var directMode by state.directMode
    var message by state.message
    var busy by state.busy
    var expandedGroups by state.expandedGroups
    var loadedTarget by state.loadedTarget

    fun stageRoot(extraDictionaryNames: Set<String> = emptySet()): Pair<File, DocumentFile?> {
        val saf = findSafRoot(context, targetPath)
        if (saf == null) return advancedRootFile(targetPath) to null
        val stage = File(context.cacheDir, "wanxiang_advanced_stage").apply { deleteRecursively(); mkdirs() }
        copySafToStage(context, saf, stage, extraDictionaryNames)
        return stage to saf
    }

    fun initialValues(items: List<AdvancedField>): Map<String, String> = items.associate { field ->
        field.path to if (field.type in listOf("schema_checkboxes", "scheme_checkboxes")) {
            JSONArray().apply { field.choices.filter { it.checked }.forEach { put(it.id) } }.toString()
        } else field.value
    }

    fun loadCommonForm() {
        scope.launch {
            busy = true
            runCatching {
                withContext(Dispatchers.IO) { stageRoot().first.let { AdvancedPythonBridge.common(context, it, directMode) } }
            }.onSuccess { loaded ->
                commonFields = loaded
                fields = loaded
                val initial = initialValues(loaded)
                values = initial
                baselineValues = initial
                message = "常用综合设置 · ${loaded.size} 个设置项"
            }.onFailure {
                commonFields = emptyList()
                fields = emptyList()
                message = "❌ 常用设置读取失败：${it.message}"
            }
            busy = false
        }
    }

    fun loadForm(file: AdvancedFile, section: String) {
        scope.launch {
            busy = true
            runCatching {
                withContext(Dispatchers.IO) {
                    stageRoot().first.let { AdvancedPythonBridge.form(context, it, file.name, section, directMode) }
                }
            }.onSuccess { loaded ->
                fields = loaded
                val initial = initialValues(loaded)
                values = initial
                baselineValues = initial
                message = "${file.label} · ${loaded.size} 个设置项"
            }.onFailure {
                fields = emptyList()
                message = "❌ 读取失败：${it.message}"
            }
            busy = false
        }
    }

    fun selectCommon() {
        val wasShowingCommon = showCommon
        showCommon = true
        fields = commonFields
        val initial = initialValues(commonFields)
        values = initial
        baselineValues = initial
        scope.launch { drawerState.close() }
        if (wasShowingCommon && targetPath.isNotBlank()) loadCommonForm()
    }

    fun selectCategory(category: AdvancedCategory) {
        showCommon = false
        selectedSection = category.key
        selectedFile = category.files.firstOrNull { it.name == selectedFile?.name } ?: category.files.firstOrNull()
        selectedFile?.let { file ->
            // Non-schema resource YAML has no managed *.custom.yaml target and must be edited directly.
            if (file.name != "default.yaml" && !file.name.endsWith(".schema.yaml")) directMode = true
        }
        expandedGroups = expandedGroups + category.group
        scope.launch { drawerState.close() }
    }

    fun importSwitches(field: AdvancedField) {
        scope.launch {
            runCatching {
                withContext(Dispatchers.IO) { stageRoot().first.let { AdvancedPythonBridge.importSwitches(context, it) } }
            }.onSuccess { result ->
                val json = JSONObject(result)
                values = values + (field.path to json.optString("value"))
                message = "已提取 ${json.optInt("count")} 个开关，请保存"
            }.onFailure { message = "❌ 提取失败：${it.message}" }
        }
    }

    fun scan() {
        scope.launch {
            busy = true
            runCatching {
                withContext(Dispatchers.IO) {
                    val stage = stageRoot().first
                    AdvancedPythonBridge.scan(context, stage)
                }
            }.onSuccess { loaded ->
                val wasShowingCommon = showCommon
                files = loaded
                showCommon = true
                fields = emptyList()
                values = emptyMap()
                val categories = buildAdvancedCategories(loaded)
                val first = categories.values.flatten().firstOrNull()
                selectedSection = first?.key ?: ""
                selectedFile = first?.files?.firstOrNull()
                expandedGroups = first?.let { setOf(it.group) } ?: emptySet()
                message = "已加载 ${loaded.size} 个配置文件，正在读取常用设置…"
                // 若页面原本已停留在常用设置页，showCommon 不会变化，需手动刷新；
                // 否则由 LaunchedEffect 触发一次加载，避免并发删除/重建 SAF 暂存目录。
                if (wasShowingCommon) loadCommonForm()
            }.onFailure {
                files = emptyList()
                selectedFile = null
                fields = emptyList()
                message = "❌ 扫描失败：${it.message}"
            }
            busy = false
        }
    }

    LaunchedEffect(targetPath) {
        if (targetPath.isNotBlank() && loadedTarget != targetPath) {
            loadedTarget = targetPath
            scan()
        }
    }
    LaunchedEffect(showCommon, directMode) {
        if (targetPath.isNotBlank() && showCommon) loadCommonForm()
    }
    LaunchedEffect(showCommon, selectedFile?.name, selectedSection, directMode) {
        if (targetPath.isNotBlank() && !showCommon) selectedFile?.let { loadForm(it, selectedSection) }
    }

    val categoriesByGroup = buildAdvancedCategories(files)
    val selectedCategory = if (showCommon) null else categoriesByGroup.values.flatten().firstOrNull {
        it.key == selectedSection && it.files.any { file -> file.name == selectedFile?.name }
    }
    val editorFields = if (showCommon) commonFields else fields
    val supportsPatchMode = showCommon || selectedFile?.name == "default.yaml" || selectedFile?.name?.endsWith(".schema.yaml") == true

    ModalNavigationDrawer(
        drawerState = drawerState,
        gesturesEnabled = true,
        drawerContent = {
            ModalDrawerSheet(
                drawerContainerColor = Color.White,
                modifier = Modifier.widthIn(min = 290.dp, max = 350.dp)
            ) {
                Column(Modifier.fillMaxSize()) {
                    Row(
                        Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 18.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text("高级设置目录", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
                            Text("同一分类已合并，进入后切换方案", fontSize = 11.sp, color = Color.Gray)
                        }
                        TextButton(onClick = { scope.launch { drawerState.close() } }) { Text("关闭") }
                    }
                    Divider(color = MorandiLightGreen)
                    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(vertical = 8.dp)) {
                        TextButton(
                            onClick = { selectCommon() },
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp),
                            contentPadding = PaddingValues(horizontal = 10.dp, vertical = 7.dp)
                        ) {
                            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                Text(if (showCommon) "●" else "○", color = if (showCommon) MorandiGreen else Color.LightGray, modifier = Modifier.padding(end = 8.dp))
                                Text("🌟 常用综合设置", modifier = Modifier.weight(1f), fontSize = 14.sp, fontWeight = FontWeight.Bold, color = if (showCommon) MorandiDarkGreen else Color.DarkGray)
                                Text("跨文件", fontSize = 10.sp, color = Color.Gray)
                            }
                        }
                        Divider(color = MorandiLightGreen, modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp))
                        categoriesByGroup.forEach { (group, categories) ->
                            val groupOpen = group in expandedGroups
                            TextButton(
                                onClick = { expandedGroups = if (groupOpen) expandedGroups - group else expandedGroups + group },
                                modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp),
                                contentPadding = PaddingValues(horizontal = 10.dp, vertical = 5.dp)
                            ) {
                                Text(if (groupOpen) "⌄  $group" else "›  $group", modifier = Modifier.fillMaxWidth(), fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
                            }
                            if (groupOpen) categories.forEach { category ->
                                val selected = selectedCategory?.group == category.group && selectedCategory.key == category.key
                                TextButton(
                                    onClick = { selectCategory(category) },
                                    modifier = Modifier.fillMaxWidth().padding(start = 28.dp, end = 8.dp),
                                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 6.dp)
                                ) {
                                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                        Text(if (selected) "●" else "○", color = if (selected) MorandiGreen else Color.LightGray, modifier = Modifier.padding(end = 8.dp))
                                        Text(category.title, modifier = Modifier.weight(1f), fontSize = 13.sp, fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal, color = if (selected) MorandiDarkGreen else Color.DarkGray, maxLines = 2, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    ) {
        Column(Modifier.fillMaxSize().background(Color(0xFFF8FAF8))) {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                TextButton(onClick = { scope.launch { drawerState.open() } }, contentPadding = PaddingValues(horizontal = 8.dp)) {
                    Text("☰", fontSize = 24.sp, color = MorandiDarkGreen)
                }
                Column(Modifier.weight(1f)) {
                    Text("🛠️ 高级设置", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
                    Text(
                        selectedCategory?.title ?: "从左侧选择设置分类",
                        fontSize = 11.sp,
                        color = Color.Gray,
                        maxLines = 1,
                        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis
                    )
                }
                TextButton(onClick = { scan() }, enabled = !busy, contentPadding = PaddingValues(horizontal = 8.dp)) { Text("刷新") }
            }
            Divider(color = MorandiLightGreen)

            Card(
                Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
                colors = CardDefaults.cardColors(containerColor = Color.White),
                border = CardDefaults.outlinedCardBorder(true)
            ) {
                Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("配置目录", fontWeight = FontWeight.Bold, color = MorandiDarkGreen)
                            Text(
                                when {
                                    targetPath == "DEFAULT" -> "默认 /rime"
                                    isRootTarget(targetPath) -> "Root ${rootTargetPath(targetPath)}"
                                    targetPath.isBlank() -> "未选择"
                                    else -> "SAF 授权目录"
                                },
                                fontSize = 11.sp,
                                color = Color.Gray,
                                maxLines = 1,
                                overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis
                            )
                        }
                        OutlinedButton(onClick = { onTargetPathChange("DEFAULT") }, contentPadding = PaddingValues(horizontal = 8.dp)) { Text("默认") }
                        Spacer(Modifier.width(6.dp))
                        OutlinedButton(onClick = onPickSafDirectory, contentPadding = PaddingValues(horizontal = 8.dp)) { Text("SAF") }
                    }
                    Row(Modifier.fillMaxWidth().padding(top = 5.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                        FilterChip(selected = !directMode, onClick = { directMode = false }, enabled = supportsPatchMode, label = { Text("补丁模式") })
                        FilterChip(selected = directMode, onClick = { directMode = true }, label = { Text("直写模式") })
                        Spacer(Modifier.weight(1f))
                        Text(message, fontSize = 10.sp, color = Color.Gray, maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
                    }
                }
            }

            if (!showCommon && (selectedCategory == null || selectedFile == null)) {
                Column(Modifier.fillMaxSize().padding(28.dp), verticalArrangement = Arrangement.Center) {
                    Text("请点击左上角 ☰，从配置目录中选择设置分类", color = Color.Gray)
                }
            } else {
                Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 12.dp)) {
                    Text(if (showCommon) "🌟 常用综合设置" else selectedCategory!!.title, fontSize = 18.sp, fontWeight = FontWeight.Bold, color = MorandiDarkGreen, modifier = Modifier.padding(vertical = 6.dp))
                    Text(if (showCommon) "候选数、自动调频、启用方案、词库、反查和超级提示统一管理" else selectedFile!!.label, fontSize = 11.sp, color = Color.Gray)
                    if (editorFields.isEmpty() && !busy) Text("该分类没有可编辑字段", color = Color.Gray, modifier = Modifier.padding(top = 10.dp))
                    editorFields.forEach { field ->
                        val current = values[field.path] ?: ""
                        if (field.type in listOf("schema_checkboxes", "scheme_checkboxes")) {
                            val selectedIds = runCatching {
                                val array = JSONArray(current)
                                (0 until array.length()).map { array.optString(it) }.toSet()
                            }.getOrDefault(emptySet())
                            Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                                Text(field.title, fontWeight = FontWeight.Bold)
                                if (field.desc.isNotBlank()) Text(field.desc, fontSize = 11.sp, color = Color.Gray)
                                field.choices.forEach { choice ->
                                    Row(Modifier.fillMaxWidth().padding(top = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                                        Checkbox(
                                            checked = choice.id in selectedIds,
                                            onCheckedChange = { checked ->
                                                if (field.type == "schema_checkboxes" && !checked && selectedIds.size <= 1) {
                                                    message = "至少需要保留一个启用方案"
                                                } else {
                                                    val next = selectedIds.toMutableSet().apply { if (checked) add(choice.id) else remove(choice.id) }
                                                    values = values + (field.path to JSONArray().apply { next.forEach { put(it) } }.toString())
                                                }
                                            }
                                        )
                                        Column(Modifier.weight(1f)) {
                                            Text(choice.label, fontWeight = FontWeight.Medium)
                                            Text(choice.id, fontSize = 10.sp, color = Color.Gray)
                                        }
                                    }
                                }
                            }
                        } else if (field.type in setOf("dynamic_list", "dynamic_block_list", "algebra_patch",
                                "reverse_algebra", "english_algebra", "mixed_algebra", "list_text",
                                "dynamic_map", "dynamic_kv_list")) {
                            AdvancedStructuredEditor(field, current) { next ->
                                values = values + (field.path to next)
                            }
                        } else if (field.type == "bool") {
                            Row(Modifier.fillMaxWidth().padding(vertical = 5.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                                Column(Modifier.weight(1f)) { Text(field.title, fontWeight = FontWeight.Bold); if (field.desc.isNotBlank()) Text(field.desc, fontSize = 11.sp, color = Color.Gray) }
                                Switch(checked = current.equals("true", true), onCheckedChange = { v -> values = values + (field.path to v.toString()) })
                            }
                        } else if (field.type == "select" && field.options.isNotEmpty()) {
                            Column(Modifier.fillMaxWidth().padding(vertical = 5.dp)) {
                                Text(field.title, fontWeight = FontWeight.Bold)
                                if (field.desc.isNotBlank()) Text(field.desc, fontSize = 11.sp, color = Color.Gray)
                                Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                                    field.options.forEach { option -> FilterChip(selected = current == option, onClick = { values = values + (field.path to option) }, label = { Text(option, fontSize = 11.sp) }) }
                                }
                            }
                        } else {
                            Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
                                    OutlinedTextField(
                                        value = current,
                                        onValueChange = { values = values + (field.path to it) },
                                        label = { Text(field.title) },
                                        supportingText = { if (field.desc.isNotBlank()) Text(field.desc) },
                                        modifier = Modifier.weight(1f),
                                        minLines = if (field.type in listOf("multiline_str", "list_text", "dynamic_list", "algebra_patch", "reverse_algebra", "english_algebra", "mixed_algebra", "dynamic_map", "raw_yaml", "dynamic_block_list", "dynamic_kv_list")) 3 else 1,
                                        singleLine = field.type !in listOf("multiline_str", "list_text", "dynamic_list", "algebra_patch", "reverse_algebra", "english_algebra", "mixed_algebra", "dynamic_map", "raw_yaml", "dynamic_block_list", "dynamic_kv_list"),
                                        keyboardOptions = if (field.type in listOf("int", "float", "number")) KeyboardOptions(keyboardType = KeyboardType.Number) else KeyboardOptions.Default,
                                        textStyle = LocalTextStyle.current.copy(fontSize = 13.sp)
                                    )
                                    if (field.actionButton.isNotBlank()) {
                                        TextButton(onClick = { importSwitches(field) }, modifier = Modifier.padding(top = 6.dp)) { Text(field.actionButton, fontSize = 11.sp) }
                                    }
                                }
                            }
                        }
                    }
                    Button(
                        onClick = {
                            if (!showCommon && selectedFile == null) return@Button
                            scope.launch {
                                val dirtyValues = values.filter { (key, value) -> baselineValues[key] != value }
                                if (dirtyValues.isEmpty()) {
                                    message = "没有修改项"
                                    return@launch
                                }
                                busy = true
                                message = "正在校验并保存…"
                                runCatching {
                                    withContext(Dispatchers.IO) {
                                        val requestedDictionaryNames = dirtyValues
                                            .filterKeys { it in setOf("translator/dictionary", "phrase_dict", "abbrev_dict") }
                                            .values.filter { it.replace("_", "").isNotEmpty() && it.all { ch -> ch == '_' || ch.isLetterOrDigit() } }
                                            .map { "$it.dict.yaml" }.toSet()
                                        val (stage, saf) = stageRoot(
                                            requestedDictionaryNames + setOf(
                                                "wanxiang.dict.yaml", "wanxiang_lite.dict.yaml",
                                                "wanxiang_pro.dict.yaml", "custom_phrase.dict.yaml", "wanxiang_abbrev.dict.yaml"
                                            )
                                        )
                                        val result = if (showCommon) {
                                            AdvancedPythonBridge.saveCommon(context, stage, directMode, dirtyValues)
                                        } else {
                                            val file = selectedFile ?: error("未选择配置文件")
                                            AdvancedPythonBridge.save(context, stage, file.name, selectedSection, directMode, dirtyValues)
                                        }
                                        if (saf != null) {
                                            syncAdvancedStageToSaf(context, saf, stage,
                                                JSONArray(JSONObject(result).optString("changed", "[]")))
                                        }
                                        result
                                    }
                                }.onSuccess { result ->
                                    val json = JSONObject(result)
                                    message = "✅ ${json.optString("message")}：${JSONArray(json.optString("changed", "[]")).join(", ")}"
                                    baselineValues = values.toMap()
                                }.onFailure { message = "❌ 保存失败：${it.message}" }
                                busy = false
                            }
                        },
                        enabled = !busy,
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 16.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = MorandiGreen)
                    ) { Text(if (busy) "处理中…" else "💾 保存当前分类") }
                }
            }
        }
    }
}
