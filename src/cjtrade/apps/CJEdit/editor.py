import os

class EditorBase:
    def __init__(self, app: str = "vim", file: str = "", prehook: str = ""):
        self.main_editor = app
        self.target_file = file
        self.prehook = prehook
        self.comp_cmdline = f"{prehook} {self.main_editor} {self.target_file}"

    def write_template(self, template_str):
        with open(file=self.target_file, mode="w") as f:
            f.write(template_str)

    def launch(self):
        os.system(self.comp_cmdline)


class VSCode(EditorBase):
    def __init__(self, app = "code", file: str = ""):
        prehook = "PATH=$HOME/Downloads/gitrepo/CJTrade/.venv/bin:$PATH"  # TODO: remove personal dir
        super().__init__(app=app, file=file, prehook=prehook)
        self.comp_cmdline += " --wait"  # For blocking file open

class SublimeText(EditorBase):
    def __init__(self, app = "subl", file: str = ""):
        prehook = "PATH=$HOME/Downloads/gitrepo/CJTrade/.venv/bin:$PATH"  # TODO: remove personal dir
        super().__init__(app=app, file=file, prehook=prehook)
        self.comp_cmdline += " --wait"  # For blocking file open
        self.comp_cmdline += " --new-window"  # Avoid open in an existing window

class Vim(EditorBase):
    def __init__(self, app = "vim", file: str = ""):
        prehook = "PATH=$HOME/Downloads/gitrepo/CJTrade/.venv/bin:$PATH"  # TODO: remove personal dir
        super().__init__(app=app, file=file, prehook=prehook)

class Nano(EditorBase):
    def __init__(self, app = "nano", file: str = ""):
        prehook = "PATH=$HOME/Downloads/gitrepo/CJTrade/.venv/bin:$PATH"  # TODO: remove personal dir
        super().__init__(app=app, file=file, prehook=prehook)

class GEdit(EditorBase):
    def __init__(self, app = "gedit", file: str = ""):
        prehook = "PATH=$HOME/Downloads/gitrepo/CJTrade/.venv/bin:$PATH"  # TODO: remove personal dir
        super().__init__(app=app, file=file, prehook=prehook)
        self.comp_cmdline += " --standalone"  # For blocking file open


class CJEditor:
    def __init__(self, app: str = "vim", file: str = "", template_str: str = ""):
        self.app_choosen = app
        self.available_apps = ["vscode", "sublime", "vim", "nano", "gedit"]
        self.instance = None
        if self.app_choosen not in self.available_apps:
            self.app_choosen = "vim"

        if self.app_choosen == "vscode":
            self.instance = VSCode(app="code", file=file)
        elif self.app_choosen == "sublime":
            self.instance = SublimeText(app="subl", file=file)
        elif self.app_choosen == "vim":
            self.instance = Vim(app="vim", file=file)
        elif self.app_choosen == "nano":
            self.instance = Nano(app="nano", file=file)
        elif self.app_choosen == "gedit":
            self.instance = GEdit(app="gedit", file=file)
        else:
            pass

        self.instance.write_template(template_str=template_str)

    def list_available_apps(self):
        return self.available_apps

    def run(self):
        self.instance.launch()
