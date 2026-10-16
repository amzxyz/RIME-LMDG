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
    fun form(context: Context, root: File, file: String, section: String): List<AdvancedField> {
        val text = python(context).getModule("advanced_settings_mobile")
            .callAttr("load_form", root.absolutePath, file, section).toString()
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
    fun common(context: Context, root: File): List<AdvancedField> {
        val text = python(context).getModule("advanced_settings_mobile")
            .callAttr("load_common_settings", root.absolutePath).toString()
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

class AdvancedSettingsMemory {
    val files = mutableStateOf<List<AdvancedFile>>(emptyList())
    val selectedFile = mutableStateOf<AdvancedFile?>(null)
    val selectedSection = mutableStateOf("")
    val fields = mutableStateOf<List<AdvancedField>>(emptyList())
    val commonFields = mutableStateOf<List<AdvancedField>>(emptyList())
    val values = mutableStateOf<Map<String, String>>(emptyMap())
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
    var showCommon by state.showCommon
    var directMode by state.directMode
    var message by state.message
    var busy by state.busy
    var expandedGroups by state.expandedGroups
    var loadedTarget by state.loadedTarget

    fun stageRoot(): Pair<File, DocumentFile?> {
        val saf = findSafRoot(context, targetPath)
        if (saf == null) return advancedRootFile(targetPath) to null
        val stage = File(context.cacheDir, "wanxiang_advanced_stage").apply { deleteRecursively(); mkdirs() }
        copySafToStage(context, saf, stage)
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
                withContext(Dispatchers.IO) { stageRoot().first.let { AdvancedPythonBridge.common(context, it) } }
            }.onSuccess { loaded ->
                commonFields = loaded
                fields = loaded
                values = initialValues(loaded)
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
                    stageRoot().first.let { AdvancedPythonBridge.form(context, it, file.name, section) }
                }
            }.onSuccess { loaded ->
                fields = loaded
                values = initialValues(loaded)
                message = "${file.label} · ${loaded.size} 个设置项"
            }.onFailure {
                fields = emptyList()
                message = "❌ 读取失败：${it.message}"
            }
            busy = false
        }
    }

    fun selectCommon() {
        showCommon = true
        fields = commonFields
        values = initialValues(commonFields)
        scope.launch { drawerState.close() }
    }

    fun selectCategory(category: AdvancedCategory) {
        showCommon = false
        selectedSection = category.key
        selectedFile = category.files.firstOrNull { it.name == selectedFile?.name } ?: category.files.firstOrNull()
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
                // 目录树先显示，综合设置单独加载，避免一个慢页面阻塞左侧目录。
                loadCommonForm()
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
    LaunchedEffect(showCommon, selectedFile?.name, selectedSection, directMode) {
        if (!showCommon) selectedFile?.let { loadForm(it, selectedSection) }
    }

    val categoriesByGroup = buildAdvancedCategories(files)
    val selectedCategory = if (showCommon) null else categoriesByGroup.values.flatten().firstOrNull {
        it.key == selectedSection && it.files.any { file -> file.name == selectedFile?.name }
    }
    val editorFields = if (showCommon) commonFields else fields

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
                        FilterChip(selected = !directMode, onClick = { directMode = false }, label = { Text("补丁模式") })
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
                                                if (!checked && selectedIds.size <= 1) {
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
                                busy = true
                                message = "正在校验并保存…"
                                runCatching {
                                    withContext(Dispatchers.IO) {
                                        val (stage, saf) = stageRoot()
                                        val result = if (showCommon) {
                                            AdvancedPythonBridge.saveCommon(context, stage, directMode, values)
                                        } else {
                                            val file = selectedFile ?: error("未选择配置文件")
                                            AdvancedPythonBridge.save(context, stage, file.name, selectedSection, directMode, values)
                                        }
                                        if (saf != null) stage.listFiles().filter { it.isFile && it.name.endsWith(".yaml", true) }.forEach { copyStageFileToSaf(context, saf, it) }
                                        result
                                    }
                                }.onSuccess { result ->
                                    val json = JSONObject(result)
                                    message = "✅ ${json.optString("message")}：${JSONArray(json.optString("changed", "[]")).join(", ")}"
                                    if (showCommon) loadCommonForm()
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
