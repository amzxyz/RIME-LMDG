package com.wanxiangupdater

import android.content.Context
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private enum class PinyinToolMode {
    WINDOW,
    PATH
}

private object PinyinPythonBridge {
    private val startLock = Any()

    private fun getPython(context: Context): Python {
        if (!Python.isStarted()) {
            synchronized(startLock) {
                if (!Python.isStarted()) {
                    Python.start(AndroidPlatform(context.applicationContext))
                }
            }
        }
        return Python.getInstance()
    }

    suspend fun convertText(context: Context, text: String): Result<String> =
        withContext(Dispatchers.Default) {
            runCatching {
                getPython(context)
                    .getModule("pinyin_bridge")
                    .callAttr("convert_text", text)
                    .toString()
            }
        }

    suspend fun convertFile(
        context: Context,
        inputPath: String,
        outputPath: String
    ): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            getPython(context)
                .getModule("pinyin_bridge")
                .callAttr("convert_file", inputPath, outputPath)
                .toString()
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PinyinToolScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var mode by remember { mutableStateOf(PinyinToolMode.WINDOW) }

    var sourceText by remember { mutableStateOf("") }
    var resultText by remember { mutableStateOf("") }
    var windowBusy by remember { mutableStateOf(false) }
    var windowError by remember { mutableStateOf("") }

    var inputPath by remember { mutableStateOf("") }
    var outputPath by remember { mutableStateOf("") }
    var pathBusy by remember { mutableStateOf(false) }
    var pathStatus by remember { mutableStateOf("") }
    var pathError by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState())
    ) {
        Text(
            "🔤 拼音转换",
            fontSize = 20.sp,
            fontWeight = FontWeight.Bold,
            color = MorandiDarkGreen
        )
        Text(
            "窗口模式适合临时转换；路径模式适合直接处理 UTF-8 文本文件。",
            fontSize = 12.sp,
            color = Color.Gray
        )

        Spacer(modifier = Modifier.height(12.dp))

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            FilterChip(
                selected = mode == PinyinToolMode.WINDOW,
                onClick = { mode = PinyinToolMode.WINDOW },
                label = { Text("窗口转换") },
                modifier = Modifier.weight(1f)
            )
            FilterChip(
                selected = mode == PinyinToolMode.PATH,
                onClick = { mode = PinyinToolMode.PATH },
                label = { Text("路径转换") },
                modifier = Modifier.weight(1f)
            )
        }

        Spacer(modifier = Modifier.height(12.dp))

        if (mode == PinyinToolMode.WINDOW) {
            Card(
                colors = CardDefaults.cardColors(containerColor = Color.White),
                border = CardDefaults.outlinedCardBorder(true),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text(
                        "窗口转换",
                        fontWeight = FontWeight.Bold,
                        color = Color.DarkGray
                    )
                    Spacer(modifier = Modifier.height(8.dp))

                    OutlinedTextField(
                        value = sourceText,
                        onValueChange = { sourceText = it },
                        label = { Text("汉字") },
                        placeholder = { Text("可输入或粘贴多行汉字") },
                        modifier = Modifier.fillMaxWidth().heightIn(min = 150.dp),
                        minLines = 6
                    )

                    Spacer(modifier = Modifier.height(10.dp))

                    Button(
                        onClick = {
                            if (sourceText.isBlank()) return@Button

                            scope.launch {
                                windowBusy = true
                                windowError = ""

                                PinyinPythonBridge.convertText(context, sourceText)
                                    .onSuccess { resultText = it }
                                    .onFailure {
                                        resultText = ""
                                        windowError = it.message ?: it.javaClass.simpleName
                                    }

                                windowBusy = false
                            }
                        },
                        enabled = !windowBusy && sourceText.isNotBlank(),
                        colors = ButtonDefaults.buttonColors(containerColor = MorandiGreen),
                        modifier = Modifier.align(Alignment.CenterHorizontally)
                    ) {
                        Text(if (windowBusy) "转换中…" else "转换")
                    }

                    Spacer(modifier = Modifier.height(10.dp))

                    OutlinedTextField(
                        value = resultText,
                        onValueChange = {},
                        readOnly = true,
                        label = { Text("拼音") },
                        placeholder = { Text("带声调拼音，音节以空格分隔") },
                        modifier = Modifier.fillMaxWidth().heightIn(min = 150.dp),
                        minLines = 6
                    )

                    AnimatedVisibility(visible = windowError.isNotBlank()) {
                        Text(
                            "转换失败：$windowError",
                            fontSize = 12.sp,
                            color = Color(0xFFC46A6A),
                            modifier = Modifier.padding(top = 8.dp)
                        )
                    }
                }
            }
        } else {
            Card(
                colors = CardDefaults.cardColors(containerColor = Color.White),
                border = CardDefaults.outlinedCardBorder(true),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text(
                        "路径转换",
                        fontWeight = FontWeight.Bold,
                        color = Color.DarkGray
                    )
                    Text(
                        "填写应用有权限访问的绝对路径。输入文件按 UTF-8 读取，结果按 UTF-8 写出。",
                        fontSize = 11.sp,
                        color = Color.Gray,
                        modifier = Modifier.padding(top = 2.dp, bottom = 10.dp)
                    )

                    OutlinedTextField(
                        value = inputPath,
                        onValueChange = {
                            inputPath = it
                            pathStatus = ""
                            pathError = ""
                        },
                        label = { Text("输入文件路径") },
                        placeholder = {
                            Text("/storage/emulated/0/Download/chinese.txt")
                        },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )

                    Spacer(modifier = Modifier.height(8.dp))

                    OutlinedTextField(
                        value = outputPath,
                        onValueChange = {
                            outputPath = it
                            pathStatus = ""
                            pathError = ""
                        },
                        label = { Text("输出文件路径") },
                        placeholder = {
                            Text("/storage/emulated/0/Download/pinyin.txt")
                        },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )

                    Spacer(modifier = Modifier.height(12.dp))

                    Button(
                        onClick = {
                            val input = inputPath.trim()
                            val output = outputPath.trim()
                            if (input.isBlank() || output.isBlank()) return@Button

                            scope.launch {
                                pathBusy = true
                                pathStatus = ""
                                pathError = ""

                                PinyinPythonBridge.convertFile(
                                    context = context,
                                    inputPath = input,
                                    outputPath = output
                                ).onSuccess {
                                    pathStatus = it.ifBlank { "转换完成" }
                                }.onFailure {
                                    pathError = it.message ?: it.javaClass.simpleName
                                }

                                pathBusy = false
                            }
                        },
                        enabled = !pathBusy &&
                            inputPath.isNotBlank() &&
                            outputPath.isNotBlank(),
                        colors = ButtonDefaults.buttonColors(containerColor = MorandiGreen),
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(8.dp)
                    ) {
                        Text(if (pathBusy) "正在转换…" else "转换文件")
                    }

                    AnimatedVisibility(visible = pathStatus.isNotBlank()) {
                        Text(
                            "✅ $pathStatus",
                            fontSize = 12.sp,
                            color = MorandiDarkGreen,
                            modifier = Modifier.padding(top = 10.dp)
                        )
                    }

                    AnimatedVisibility(visible = pathError.isNotBlank()) {
                        Text(
                            "❌ $pathError",
                            fontSize = 12.sp,
                            color = Color(0xFFC46A6A),
                            modifier = Modifier.padding(top = 10.dp)
                        )
                    }

                    Text(
                        "说明：Android 的存储权限仍然生效；Chaquopy 不会因为应用具有 RootShell 功能而自动获得 root 文件访问权限。",
                        fontSize = 10.sp,
                        color = Color.Gray,
                        modifier = Modifier.padding(top = 12.dp)
                    )
                }
            }
        }
    }
}
