#Requires AutoHotkey v2.0

; # → Win 键
; ! → Alt 键
; ^ → Ctrl 键
; + → Shift 键

GetRimeVersion() {
    yamlPath := A_ScriptDir "\..\installation.yaml"
    if !FileExist(yamlPath) {
        MsgBox "配置文件不存在：" yamlPath
        return ""
    }

    version := ""
    Loop Read, yamlPath {
        if RegExMatch(A_LoopReadLine, "^\s*distribution_version:\s*(.+)", &m) {
            version := Trim(m[1])
            break
        }
    }
    return version
}

GetWeaselPath(type) {
    version := GetRimeVersion()
    if version = "" {
        MsgBox "无法读取 Rime 版本号"
        return ""
    }

    if type = "server" {
        return "C:\Program Files\Rime\weasel-" version "\WeaselServer.exe"
    }

    if type = "deployer" {
        return "C:\Program Files\Rime\weasel-" version "\WeaselDeployer.exe"
    }

    if type = "setup" {
        return "C:\Program Files\Rime\weasel-" version "\WeaselSetup.exe"
    }
}

; 获取执行路径
weaselServerPath := GetWeaselPath('server')
; if weaselServerPath != "" {
;     MsgBox "Weasel 路径为: " weaselServerPath
;     ; Run weaselServerPath ; 如果需要运行
; }
weaselDeployerPath := GetWeaselPath('deployer')
weaselSetupPath := GetWeaselPath('setup')

; 重启 Rime 服务
^p::
{
    Run weaselServerPath
    return
}

; 重新部署
+!d::
{
    Run weaselDeployerPath " /deploy"
    return
}

; 用户资料同步
+!a::
{
    Run weaselDeployerPath " /sync"
    return
}

; 打开输入法设定
+!c::
{
    Run weaselSetupPath
    return
}

; 添加用户词
+!u::
{
    Run "notepad.exe C:\Users\jack\AppData\Roaming\Rime\lua\user_words.lua"
    return
}

; 插入定制词
+!i::
{
    Run "notepad.exe C:\Users\jack\AppData\Roaming\Rime\custom_pinyin.txt"
    return
}
