// 今天摸了吗 · Windows 启动器
//
// 这是一个真正的 Windows GUI 可执行文件（PE），双击后无控制台闪烁，
// 直接唤起同目录 runtime\pythonw.exe 运行 runtime\app\main.py，
// 随即退出，由「今天摸了吗」主程序接管（主程序自带托盘与单实例检查）。
//
// 交叉编译（在 macOS / Linux 上，需 Go 1.20+）：
//   GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -ldflags="-H windowsgui -s -w" -o 今天摸了吗.exe .
//
// 之所以这样分层：PyInstaller 不能跨平台产出 Windows exe，而 Python
// embeddable + Qt 运行库需要随包分发；本启动器把「双击 exe」这一步补上，
// 用户不必再去找 .bat 文件。
package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"unsafe"
)

func alert(msg string) {
	user32 := syscall.NewLazyDLL("user32.dll")
	messageBox := user32.NewProc("MessageBoxW")
	title, _ := syscall.UTF16PtrFromString("今天摸了吗")
	text, _ := syscall.UTF16PtrFromString(msg)
	// MB_ICONERROR = 0x10
	messageBox.Call(0, uintptr(unsafe.Pointer(text)), uintptr(unsafe.Pointer(title)), 0x10)
}

func main() {
	exe, err := os.Executable()
	if err != nil {
		alert("无法定位程序路径，请确认压缩包已完整解压。")
		return
	}
	dir := filepath.Dir(exe)
	python := filepath.Join(dir, "runtime", "pythonw.exe")
	script := filepath.Join(dir, "runtime", "app", "main.py")

	if _, err := os.Stat(python); err != nil {
		alert("缺少 runtime\\pythonw.exe：请把压缩包里的所有文件解压到同一个目录，不要只复制 exe。")
		return
	}
	if _, err := os.Stat(script); err != nil {
		alert("缺少 runtime\\app\\main.py：请重新解压完整压缩包。")
		return
	}

	args := append([]string{script}, os.Args[1:]...)
	cmd := exec.Command(python, args...)
	// CREATE_NO_WINDOW：不弹黑色控制台；pythonw 本身也是 GUI 子系统
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	cmd.Stdin = nil
	cmd.Stdout = nil
	cmd.Stderr = nil
	if err := cmd.Start(); err != nil {
		alert("启动失败：" + err.Error() + "\n\n可改用 Run-Debug.bat 查看详细报错。")
	}
}
