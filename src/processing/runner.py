from typing import Optional


class ProcessResult:
    def __init__(self, output_path: Optional[str] = None, error: str = "", stdout: str = "",
                 stderr: str = "", output_paths: Optional[dict[str, str]] = None):
        self.output_path = output_path
        self.error = error
        self.stdout = stdout
        self.stderr = stderr
        self.output_paths = output_paths or {}

    @property
    def success(self) -> bool:
        return self.output_path is not None or bool(self.output_paths)

    @property
    def verbose_output(self) -> str:
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(self.stderr)
        return "\n".join(parts)
