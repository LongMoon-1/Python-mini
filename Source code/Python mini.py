# python_mini.py

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import sys
import os
import io
import traceback
import re
import threading
import queue
import time

# ==================== 自定义标准输入输出重定向 ====================
class TkinterOutput(io.StringIO):
    """将 stdout/stderr 重定向到 tkinter Text 组件（线程安全，支持窗口销毁检测）"""
    def __init__(self, text_widget, tag=None, parent_window=None):
        super().__init__()
        self.text_widget = text_widget
        self.tag = tag
        self.parent_window = parent_window

    def write(self, s):
        if not s:
            return
        if self.parent_window and not self.parent_window.winfo_exists():
            return
        self.text_widget.after(0, lambda: self._insert(s))
        return len(s)

    def _insert(self, s):
        try:
            self.text_widget.insert(tk.END, s, self.tag)
            self.text_widget.see(tk.END)
        except tk.TclError:
            pass

    def flush(self):
        pass


class TkinterInput:
    """模拟 input()，通过 tkinter Entry 获取用户输入"""
    def __init__(self, entry_widget, submit_event, prompt_label=None, parent_window=None):
        self.entry = entry_widget
        self.submit_event = submit_event
        self.prompt_label = prompt_label
        self.parent_window = parent_window
        self._input_queue = queue.Queue()
        self._waiting = False

    def readline(self):
        self._waiting = True
        self.entry.after(0, self._activate_input_mode)
        self.submit_event.wait()
        self.submit_event.clear()
        self._waiting = False
        line = self._input_queue.get()
        return line + '\n'

    def _activate_input_mode(self):
        if self.parent_window and not self.parent_window.winfo_exists():
            return
        self.entry.config(state='normal')
        self.entry.focus_set()
        if self.prompt_label:
            self.prompt_label.config(text='输入: ')

    def submit(self, value):
        if self._waiting:
            self._input_queue.put(value)
            self.submit_event.set()
            self.entry.delete(0, tk.END)
            self.entry.config(state='disabled')
            if self.prompt_label:
                self.prompt_label.config(text='>>> ')

    def is_waiting(self):
        return self._waiting


# ==================== 模拟终端窗口 ====================
class TerminalWindow:
    def __init__(self, master=None, code_to_run=None, file_to_run=None):
        self.window = tk.Toplevel(master)
        self.window.title("Python终端")
        self.window.geometry("900x600")
        self.window.configure(bg="black")
        
        self.is_running_code = False
        self._force_close = False
        self.window.protocol("WM_DELETE_WINDOW", self.on_close_request)
        self.window.bind('<Alt-F4>', lambda e: self.on_close_request())
        
        # 终端显示区域
        self.terminal = scrolledtext.ScrolledText(
            self.window, bg="black", fg="#00ff00", insertbackground="white",
            font=("Consolas", 10), wrap=tk.WORD
        )
        self.terminal.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.terminal.tag_config("input", foreground="#00ff00")
        self.terminal.tag_config("output", foreground="#ffffff")
        self.terminal.tag_config("error", foreground="#ff4444")
        self.terminal.tag_config("prompt", foreground="#00ff00")
        self.terminal.tag_config("info", foreground="#00aaff")

        # 输入行
        input_frame = tk.Frame(self.window, bg="black")
        input_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        self.prompt_label = tk.Label(input_frame, text=">>> ", bg="black", fg="#00ff00", font=("Consolas", 10))
        self.prompt_label.pack(side=tk.LEFT)

        self.input_entry = tk.Entry(input_frame, bg="black", fg="#00ff00",
                                    insertbackground="white", font=("Consolas", 10))
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.input_entry.bind('<Return>', self.on_enter_pressed)
        self.input_entry.bind('<Up>', self.history_up)
        self.input_entry.bind('<Down>', self.history_down)

        # 按钮栏
        button_frame = tk.Frame(self.window, bg="black")
        button_frame.pack(fill=tk.X, padx=5, pady=5)

        tk.Button(button_frame, text="清空终端", command=self.clear_terminal,
                  bg="#333", fg="white", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(button_frame, text="中断执行", command=self.interrupt_execution,
                  bg="#333", fg="white", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)
        tk.Button(button_frame, text="重置命名空间", command=self.reset_namespace,
                  bg="#333", fg="white", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        self.status_label = tk.Label(self.window, text="就绪", bg="black", fg="#888888", anchor=tk.W)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=2)

        # 终端状态
        self.namespace = {'__name__': '__main__', '__builtins__': __builtins__}
        self.history = []
        self.history_index = 0
        self.running = True
        self.execution_thread = None
        self.stop_request = False

        self.input_event = threading.Event()
        self.tkinter_input = TkinterInput(self.input_entry, self.input_event, self.prompt_label, self.window)

        self.stdout_redirect = TkinterOutput(self.terminal, "output", self.window)
        self.stderr_redirect = TkinterOutput(self.terminal, "error", self.window)
        self.old_stdout = sys.stdout
        self.old_stderr = sys.stderr
        self.old_stdin = sys.stdin

        self.show_banner()

        if code_to_run:
            self.auto_run_code(code_to_run)
        elif file_to_run:
            self.auto_run_file(file_to_run)

    def show_banner(self):
        banner = f"""Python {sys.version} on {sys.platform}
Type "help", "copyright", "credits" or "license" for more information.
"""
        self.terminal.insert(tk.END, banner, "output")
        self.terminal.see(tk.END)
        self._set_command_mode()

    def _set_command_mode(self):
        if not self.running or self._force_close:
            return
        self.prompt_label.config(text=">>> ")
        self.input_entry.config(state='normal')
        self.input_entry.delete(0, tk.END)
        self.input_entry.focus_set()

    def on_enter_pressed(self, event=None):
        if self.tkinter_input.is_waiting():
            value = self.input_entry.get()
            self.tkinter_input.submit(value)
            self.terminal.insert(tk.END, f"{value}\n", "input")
            self.terminal.see(tk.END)
        else:
            command = self.input_entry.get().strip()
            if not command:
                self._set_command_mode()
                return
            self.input_entry.delete(0, tk.END)
            self.terminal.insert(tk.END, f">>> {command}\n", "input")
            if command in ('exit()', 'quit()'):
                self.on_close_request()
                return
            if command == 'clear()':
                self.clear_terminal()
                self._set_command_mode()
                return
            if command == 'reset()':
                self.reset_namespace()
                self._set_command_mode()
                return
            self.history.append(command)
            self.history_index = len(self.history)
            self._run_user_code(command)
        return "break"

    def _run_user_code(self, code):
        def target():
            self.is_running_code = True
            try:
                self._execute_code(code)
            finally:
                self.is_running_code = False
                self.window.after(0, self._set_command_mode)
        self.execution_thread = threading.Thread(target=target, daemon=True)
        self.execution_thread.start()

    def _execute_code(self, code, is_script=False):
        sys.stdout = self.stdout_redirect
        sys.stderr = self.stderr_redirect
        sys.stdin = self.tkinter_input
        try:
            if is_script:
                exec(code, self.namespace)
            else:
                try:
                    result = eval(code, self.namespace)
                    if result is not None:
                        print(repr(result))
                except SyntaxError:
                    exec(code, self.namespace)
        except SystemExit:
            pass
        except Exception:
            print(traceback.format_exc(), file=sys.stderr)
        finally:
            sys.stdout = self.old_stdout
            sys.stderr = self.old_stderr
            sys.stdin = self.old_stdin

    def auto_run_code(self, code):
        self.status_label.config(text="正在执行代码...")
        self.terminal.insert(tk.END, f"\n{'='*50}\n", "info")
        self.terminal.insert(tk.END, "执行代码:\n", "info")
        self.terminal.insert(tk.END, f"{'-'*50}\n", "info")

        def run():
            self.is_running_code = True
            try:
                self._execute_code(code, is_script=True)
            finally:
                self.is_running_code = False
                self.window.after(0, lambda: self.status_label.config(text="执行完成"))
                self.window.after(0, self._set_command_mode)

        self.execution_thread = threading.Thread(target=run, daemon=True)
        self.execution_thread.start()

    def auto_run_file(self, filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                code = f.read()
            self.auto_run_code(code)
        except Exception as e:
            self.terminal.insert(tk.END, f"读取文件失败: {e}\n", "error")
            self._set_command_mode()

    def clear_terminal(self):
        self.terminal.delete(1.0, tk.END)
        self.show_banner()

    def reset_namespace(self):
        self.namespace = {'__name__': '__main__', '__builtins__': __builtins__}
        self.terminal.insert(tk.END, "\n命名空间已重置\n", "info")

    def interrupt_execution(self):
        if self.execution_thread and self.execution_thread.is_alive():
            self.stop_request = True
            self.status_label.config(text="尝试中断...")
            self.terminal.insert(tk.END, "\n⚠️ 中断请求已发送（可能不会立即生效）\n", "error")

    def history_up(self, event):
        if self.history and self.history_index > 0:
            self.history_index -= 1
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, self.history[self.history_index])
        return "break"

    def history_down(self, event):
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, self.history[self.history_index])
        elif self.history_index == len(self.history) - 1:
            self.history_index = len(self.history)
            self.input_entry.delete(0, tk.END)
        return "break"

    def on_close_request(self):
        if self.is_running_code:
            result = messagebox.askyesno(
                "确认关闭",
                "终端正在执行代码，强制关闭可能会导致数据丢失或程序异常。\n\n确定要强制关闭吗？",
                icon='warning'
            )
            if not result:
                return
            self._force_close = True
        self.on_close()

    def on_close(self):
        self.running = False
        self.window.destroy()


# ==================== 主程序 ====================
class PythonMini:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Python mini")
        self.root.geometry("1100x700")

        self.current_scripts = []          # 侧边栏文件列表
        self.terminal_windows = []          # 打开的终端窗口
        self.current_file_path = None       # 当前编辑器关联的文件路径（用于保存到文件）

        self.setup_ui()

    def setup_ui(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="文件", menu=file_menu)
        file_menu.add_command(label="打开.py文件", command=self.open_file)
        file_menu.add_command(label="打开多个文件", command=self.open_multiple_files)
        file_menu.add_separator()
        # 新增“保存到文件”和“另存为” - 注意：保存菜单项需要保存标签字符串用于后续配置
        file_menu.add_command(label="保存到文件", command=self.save_to_file)
        file_menu.add_command(label="另存为...", command=self.save_as_file)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.quit)

        # 获取菜单项引用以便修改状态（使用标签名称）
        self.save_menu_label = "保存到文件"
        self.file_menu = file_menu  # 保存菜单对象

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="帮助", menu=help_menu)
        help_menu.add_command(label="教程", command=self.show_tutorial)
        help_menu.add_command(label="关于", command=self.show_about)

        # 左右分屏
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧文件列表
        left_frame = ttk.Frame(main_paned)
        main_paned.add(left_frame, weight=1)

        ttk.Label(left_frame, text="📁 脚本列表", font=("", 10, "bold")).pack(pady=5)

        self.file_listbox = tk.Listbox(left_frame, selectmode=tk.EXTENDED, font=("Consolas", 9))
        self.file_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.file_listbox.bind('<Double-Button-1>', self.on_file_double_click)

        file_btn_frame = ttk.Frame(left_frame)
        file_btn_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(file_btn_frame, text="➕ 添加文件", command=self.open_multiple_files).pack(side=tk.LEFT, padx=2)
        ttk.Button(file_btn_frame, text="❌ 移除选中", command=self.remove_selected_files).pack(side=tk.LEFT, padx=2)

        # 右侧编辑器
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=3)

        ttk.Label(right_frame, text="✏️ Python代码编辑器", font=("", 10, "bold")).pack(anchor=tk.W, pady=(5,0))

        self.code_input = scrolledtext.ScrolledText(right_frame, height=18, wrap=tk.WORD, font=("Consolas", 10))
        self.code_input.pack(fill=tk.BOTH, expand=True, pady=5)
        self.code_input.delete("1.0", tk.END)  # 清空初始内容

        btn_frame = ttk.Frame(right_frame)
        btn_frame.pack(fill=tk.X, pady=5)

        self.run_button = tk.Button(btn_frame, text="▶ 运行代码", command=self.run_code,
                                    bg="#4CAF50", fg="white", font=("", 11, "bold"),
                                    padx=20, pady=5, relief=tk.RAISED)
        self.run_button.pack(side=tk.LEFT, padx=5)

        ttk.Button(btn_frame, text="🪟 打开独立终端", command=self.open_terminal_window).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🗑 清空编辑器", command=self.clear_code).pack(side=tk.LEFT, padx=5)

        info_frame = ttk.Frame(right_frame)
        info_frame.pack(fill=tk.X, pady=5)
        self.file_info_label = ttk.Label(info_frame, text="", foreground="gray")
        self.file_info_label.pack(side=tk.LEFT)

        self.status_bar = ttk.Label(self.root, text="就绪 | 双击文件加载到编辑器，点击运行在终端执行", relief=tk.SUNKEN)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.code_input.bind('<Control-Return>', lambda e: self.run_code())

        # 初始状态：没有关联文件，禁用“保存到文件”
        self.update_save_menu_state()

    def update_save_menu_state(self):
        """根据 current_file_path 更新菜单项状态"""
        if self.current_file_path and os.path.exists(self.current_file_path):
            self.file_menu.entryconfig(self.save_menu_label, state='normal')
        else:
            self.file_menu.entryconfig(self.save_menu_label, state='disabled')

    def save_to_file(self):
        """保存当前编辑器内容到已关联的文件路径"""
        if not self.current_file_path:
            messagebox.showwarning("无法保存", "当前没有关联的文件，请使用“另存为”保存到新文件。")
            return
        try:
            code = self.code_input.get("1.0", tk.END).strip()
            # 保留空文件（允许清空）
            with open(self.current_file_path, 'w', encoding='utf-8') as f:
                f.write(code)
            self.status_bar.config(text=f"已保存到: {os.path.basename(self.current_file_path)}")
            self.file_info_label.config(text=f"当前文件: {os.path.basename(self.current_file_path)} (已保存)")
        except Exception as e:
            messagebox.showerror("保存失败", f"无法写入文件:\n{e}")
            self.status_bar.config(text="保存失败")

    def save_as_file(self):
        """另存为：弹出对话框，保存当前内容到新文件"""
        filepath = filedialog.asksaveasfilename(
            title="另存为",
            defaultextension=".py",
            filetypes=[("Python文件", "*.py"), ("所有文件", "*.*")]
        )
        if not filepath:
            return
        try:
            code = self.code_input.get("1.0", tk.END).strip()
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(code)
            # 更新关联路径
            self.current_file_path = filepath
            self.file_info_label.config(text=f"当前文件: {os.path.basename(filepath)}")
            self.status_bar.config(text=f"已另存为: {filepath}")
            self.update_save_menu_state()
        except Exception as e:
            messagebox.showerror("保存失败", f"无法写入文件:\n{e}")
            self.status_bar.config(text="另存为失败")

    def open_file(self):
        """打开单个文件，加载到编辑器，并记录文件路径"""
        filepath = filedialog.askopenfilename(filetypes=[("Python文件", "*.py")])
        if not filepath:
            return
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                code = f.read()
            self.code_input.delete("1.0", tk.END)
            self.code_input.insert("1.0", code)
            self.current_file_path = filepath
            self.file_info_label.config(text=f"当前文件: {os.path.basename(filepath)}")
            self.status_bar.config(text=f"已加载: {filepath}")
            self.update_save_menu_state()
        except Exception as e:
            messagebox.showerror("错误", f"无法读取文件:\n{e}")
            self.status_bar.config(text="文件读取失败")
            # 文件读取失败时不清空编辑器，但也不关联文件
            self.current_file_path = None
            self.update_save_menu_state()

    def open_multiple_files(self):
        """打开多个文件，仅添加到侧边栏，不改变当前编辑器内容"""
        filepaths = filedialog.askopenfilenames(filetypes=[("Python文件", "*.py")])
        for fp in filepaths:
            if fp not in self.current_scripts:
                self.current_scripts.append(fp)
        self.update_file_list()
        self.status_bar.config(text=f"已添加 {len(filepaths)} 个文件到列表")

    def on_file_double_click(self, event):
        """双击文件：加载到编辑器，并记录文件路径"""
        selection = self.file_listbox.curselection()
        if not selection:
            return
        idx = selection[0]
        filepath = self.current_scripts[idx]
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                code = f.read()
            self.code_input.delete("1.0", tk.END)
            self.code_input.insert("1.0", code)
            self.current_file_path = filepath
            self.file_info_label.config(text=f"当前文件: {os.path.basename(filepath)}")
            self.status_bar.config(text=f"已加载: {os.path.basename(filepath)}，点击运行按钮执行")
            self.update_save_menu_state()
        except Exception as e:
            messagebox.showerror("错误", f"无法读取文件:\n{e}")
            self.status_bar.config(text="文件读取失败")
            self.current_file_path = None
            self.update_save_menu_state()

    def clear_code(self):
        """清空编辑器，并清除当前文件关联（类似记事本新建）"""
        self.code_input.delete("1.0", tk.END)
        self.current_file_path = None
        self.file_info_label.config(text="")
        self.status_bar.config(text="编辑器已清空（未关联文件）")
        self.update_save_menu_state()

    def run_code(self):
        code = self.code_input.get("1.0", tk.END).strip()
        if not code:
            messagebox.showinfo("提示", "请输入Python代码")
            return
        self.status_bar.config(text="正在打开终端执行代码...")
        terminal = TerminalWindow(self.root, code_to_run=code)
        self.terminal_windows.append(terminal)
        self.status_bar.config(text="代码已在终端中运行")

    def open_terminal_window(self):
        terminal = TerminalWindow(self.root)
        self.terminal_windows.append(terminal)
        self.status_bar.config(text="已打开独立终端")

    def update_file_list(self):
        self.file_listbox.delete(0, tk.END)
        for script in self.current_scripts:
            self.file_listbox.insert(tk.END, os.path.basename(script))

    def remove_selected_files(self):
        selected = self.file_listbox.curselection()
        for i in reversed(selected):
            del self.current_scripts[i]
        self.update_file_list()
        self.status_bar.config(text="已移除选中文件")

    def show_tutorial(self):
        tutorial_text = """═══════════════════════════════════════════════════════════════
                      Python Mini 完全使用教程
═══════════════════════════════════════════════════════════════

【1. 概述】
Python Mini 是一个完全独立的轻量级 Python 运行环境。
- 无需在电脑上安装 Python
- 单个 exe 文件，即拷即用
- 内置标准库（包括 tkinter、sqlite3 等）
- 支持交互式命令行、运行脚本、多文件管理

【2. 主界面布局】
┌─────────────────────────────────────────────┐
│ 菜单栏：文件、帮助                            │
├──────────────┬──────────────────────────────┤
│ 左侧：脚本列表 │ 右侧：Python代码编辑器         │
│   • 添加文件  │   • 编写/粘贴代码              │
│   • 双击加载  │   • Ctrl+Enter 快速运行        │
│   • 移除文件  │   • 保存到文件 / 另存为        │
├──────────────┴──────────────────────────────┤
│ 底部：状态栏                                   │
└─────────────────────────────────────────────┘

【3. 文件操作（新增）】
- 打开 .py 文件：文件 → 打开.py文件，或双击侧边栏文件，内容加载到编辑器，并关联文件路径。
- 保存到文件：如果当前编辑器内容关联了某个文件（即通过打开或双击加载而来），点击“保存到文件”直接覆盖原文件。
- 另存为：始终可用，将当前编辑器内容保存到新位置，保存后自动关联该新文件。
- 清空编辑器：相当于“新建”，会清除当前关联，此时“保存到文件”变为灰色。

【4. 基本操作流程】

4.1 编写并运行代码
   - 方法一：直接在右侧编辑器中输入代码，点击“运行代码”或按 Ctrl+Enter。
   - 方法二：在左侧添加 .py 文件，双击文件即可将代码加载到编辑器，再运行。

4.2 使用独立终端（交互式环境）
   - 点击“打开独立终端”按钮，会弹出一个黑底绿字的终端窗口。
   - 终端完全模拟原生 Python REPL：
        >>> print("Hello")
        Hello
        >>> x = 10
        >>> x
        10
   - 支持历史命令（↑ ↓ 键）、清屏（clear()）、重置命名空间（reset()）。
   - 当代码中包含 input() 时，终端会等待用户输入，输入后按回车继续。

4.3 运行文件
   - 支持单个或多个文件批量运行。
   - 在左侧添加文件后，可以双击单个文件加载，或直接点击“运行代码”运行当前编辑器内容。
   - 运行时会自动在新终端窗口中执行，不会卡住主界面。

【5. 高级功能】

5.1 智能关闭保护
   - 如果终端窗口正在执行代码（包括等待 input()），关闭时会弹出警告。
   - 只有确认强制关闭后才会真正关闭，防止意外丢失数据。

5.2 中断执行
   - 如果代码陷入死循环或长时间无响应，可以点击“中断执行”按钮。
   - 注意：由于 Python 线程无法强制终止，中断请求不一定立即生效，建议在代码中设置检查点。

5.3 重置命名空间
   - 在终端中执行 reset() 或点击按钮，可以清空所有自定义变量，恢复到初始状态。

5.4 清屏
   - 终端中执行 clear() 或点击“清空终端”按钮，可以清除屏幕内容。

【6. 常见问题】

Q: 为什么我的代码中有 input() 但没有提示输入？
A: 请确保代码是在终端窗口中运行的（点击“运行代码”会弹出终端）。直接在主界面运行时会自动打开终端。

Q: 能否使用第三方库（如 requests、numpy）？
A: 只能使用标准库。如果需要，可以下载安装完整python解释器

Q: 终端输出有时候会“一跳一跳”而不是逐行显示？
A: 这是 tkinter GUI 的特性，不影响实际功能。所有输出最终都会正确显示。

Q: 如何彻底退出程序？
A: 关闭主窗口即可，所有打开的终端窗口也会随之关闭（或先手动关闭）。

【7. 快捷键一览】
- Ctrl+Enter        : 运行编辑器中的代码
- ↑ / ↓            : 在终端中浏览历史命令
- Alt+F4           : 关闭终端窗口（会触发智能关闭警告）

【8. 文件保存逻辑（与记事本一致）】
- 打开已有文件 → “保存到文件”可用 → 点击直接覆盖原文件。
- 清空编辑器或新建内容 → “保存到文件”禁用 → 必须使用“另存为”。
- 使用“另存为”保存新文件后，自动切换关联路径，“保存到文件”重新启用。

═══════════════════════════════════════════════════════════════
                        祝使用愉快！
═══════════════════════════════════════════════════════════════"""
        tutorial_win = tk.Toplevel(self.root)
        tutorial_win.title("Python Mini - 详细教程")
        tutorial_win.geometry("800x600")
        text_area = scrolledtext.ScrolledText(tutorial_win, wrap=tk.WORD, font=("Consolas", 10))
        text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text_area.insert(tk.END, tutorial_text)
        text_area.config(state='disabled')

    def show_about(self):
        about_text = """Python Mini v4.5

完全独立的Python运行环境，无需安装Python。

新增功能:
- 文件菜单: 保存到文件、另存为（与记事本逻辑一致）
- 打开/双击文件后，可直接保存覆盖
- 清空编辑器后自动禁用保存到文件

技术原理:
- 重定向 sys.stdin/out/err 到 tkinter 控件
- 子线程执行用户代码，避免阻塞GUI
- 使用 threading.Event + queue 实现 input() 阻塞等待
- 所有GUI更新通过 after() 调度到主线程
- 智能关闭：检测代码运行状态，防止误关闭导致崩溃

特性:
• 内置Python解释器 + tkinter
• 模拟终端支持 input() 交互
• 历史命令、清屏、重置命名空间
• 打包为单个exe，即拷即用
"""
        messagebox.showinfo("关于 Python Mini", about_text)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = PythonMini()
    app.run()