Option Explicit

Dim fso, shell, environment, scriptDir, pythonwPath, mainPath
Dim runtimeDir, logPath, command, exitCode, errorText

Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonwPath = fso.BuildPath(scriptDir, ".venv\Scripts\pythonw.exe")
mainPath = fso.BuildPath(scriptDir, "Main.py")
runtimeDir = fso.BuildPath(scriptDir, ".ari_runtime")
logPath = fso.BuildPath(runtimeDir, "launcher_error.log")

If Not fso.FileExists(pythonwPath) Then
    MsgBox "Ari virtual environment was not found." & vbCrLf & _
        "Run setup.bat from the VoiceCommand folder, then try again.", _
        vbExclamation, "Ari"
    WScript.Quit 1
End If

If Not fso.FolderExists(runtimeDir) Then
    On Error Resume Next
    fso.CreateFolder runtimeDir
    If Err.Number <> 0 Then
        errorText = Err.Description
        Err.Clear
        On Error GoTo 0
        MsgBox "Ari could not create its runtime folder." & vbCrLf & _
            runtimeDir & vbCrLf & vbCrLf & errorText, vbCritical, "Ari"
        WScript.Quit 1
    End If
    On Error GoTo 0
End If

Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = scriptDir
Set environment = shell.Environment("PROCESS")
environment("PYTHONUTF8") = "1"
environment("PYTHONIOENCODING") = "utf-8"

command = Chr(34) & shell.ExpandEnvironmentStrings("%ComSpec%") & Chr(34) & _
    " /d /s /c " & Chr(34) & Chr(34) & pythonwPath & Chr(34) & _
    " " & Chr(34) & mainPath & Chr(34) & " 2> " & _
    Chr(34) & logPath & Chr(34) & Chr(34)
exitCode = shell.Run(command, 0, True)

If exitCode <> 0 Then
    errorText = ReadUtf8Tail(logPath, 4000)
    If Len(errorText) = 0 Then
        errorText = "No error output was captured."
    End If
    MsgBox "Ari stopped with exit code " & exitCode & "." & vbCrLf & _
        "Log: " & logPath & vbCrLf & vbCrLf & errorText, vbCritical, "Ari"
End If

WScript.Quit exitCode

Function ReadUtf8Tail(filePath, maxChars)
    Dim stream, text

    ReadUtf8Tail = ""
    If Not fso.FileExists(filePath) Then Exit Function

    On Error Resume Next
    Set stream = CreateObject("ADODB.Stream")
    stream.Type = 2
    stream.Charset = "utf-8"
    stream.Open
    stream.LoadFromFile filePath
    text = stream.ReadText
    stream.Close
    If Err.Number <> 0 Then
        Err.Clear
        text = ""
    End If
    On Error GoTo 0

    If Len(text) > maxChars Then text = Right(text, maxChars)
    ReadUtf8Tail = Trim(text)
End Function
