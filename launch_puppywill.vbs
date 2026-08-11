Option Explicit

' launch_puppywill.vbs
' ---------------------
' Punto de entrada del acceso directo de escritorio. Busca "pythonw.exe" en
' el PATH del sistema (portátil: no depende de la carpeta de usuario ni de
' donde esté instalado Python en esta máquina en particular) antes de
' intentar nada; si no lo encuentra, muestra un mensaje entendible en vez
' de que Windows falle en silencio. Luego delega en run_puppywill.pyw, que
' hace la verificación de FFmpeg y los paquetes de Python.

Dim fso, shell, pythonwPath, projectDir, launcherScript

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
launcherScript = projectDir & "\run_puppywill.pyw"

Function FindPythonwOnPath()
    Dim pathEnv, dirs, i, candidate
    pathEnv = shell.ExpandEnvironmentStrings("%PATH%")
    dirs = Split(pathEnv, ";")
    For i = 0 To UBound(dirs)
        If Len(Trim(dirs(i))) > 0 Then
            candidate = fso.BuildPath(dirs(i), "pythonw.exe")
            If fso.FileExists(candidate) Then
                FindPythonwOnPath = candidate
                Exit Function
            End If
        End If
    Next
    FindPythonwOnPath = ""
End Function

pythonwPath = FindPythonwOnPath()

If pythonwPath = "" Then
    MsgBox "No se encontró Python (pythonw.exe) en el PATH del sistema." & vbCrLf & vbCrLf & _
           "Instala Python 3.10-3.12 desde https://python.org (marca 'Add python.exe to PATH' " & _
           "durante la instalación, o usa 'winget install Python.Python.3.12') y vuelve a abrir " & _
           "Puppywill AI Clipper.", _
           vbCritical, "Puppywill AI Clipper"
    WScript.Quit 1
End If

If Not fso.FileExists(launcherScript) Then
    MsgBox "No se encontró el archivo de inicio del proyecto:" & vbCrLf & launcherScript, _
           vbCritical, "Puppywill AI Clipper"
    WScript.Quit 1
End If

shell.CurrentDirectory = projectDir
' intWindowStyle = 1 (SW_SHOWNORMAL). Un 0 aqui es SW_HIDE: Qt respeta ese
' hint de arranque de Windows para la primera ventana y la deja oculta
' aunque el codigo llame a window.show() explicitamente.
shell.Run """" & pythonwPath & """ """ & launcherScript & """", 1, False
