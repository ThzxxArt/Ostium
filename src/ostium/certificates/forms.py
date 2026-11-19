"""Certificate import form shared by the console and Django admin."""

from __future__ import annotations

from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError

from ostium import paths

from .services import parse_certificate


def _staged_certificate_dirs() -> list[Path]:
    """Directories staged by the certbot deploy hook or an operator."""

    root = paths.imports_dir()
    if not root.is_dir():
        return []
    found = {cert.parent.resolve() for cert in root.glob("**/fullchain.pem") if cert.with_name("privkey.pem").is_file()}
    return sorted(found)


class CertificateImportForm(forms.Form):
    domain = forms.CharField(
        max_length=253,
        required=False,
        label="域名",
        help_text="留空时自动使用证书 SAN 的第一个域名。",
    )
    server_certificate = forms.ChoiceField(
        required=False,
        label="服务器上已暂存的证书",
        help_text="来自 /var/lib/ostium/imports 的 certbot deploy hook 暂存目录。",
    )
    certificate_file = forms.FileField(
        required=False,
        label="上传证书文件",
        help_text="PEM 格式的 fullchain/证书链。",
    )
    private_key_file = forms.FileField(
        required=False,
        label="上传私钥文件",
        help_text="PEM 格式的未加密私钥。",
    )
    certificate = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 8, "class": "mono", "spellcheck": "false"}),
        label="或粘贴证书 PEM",
        help_text="完整证书链，包含站点证书。",
    )
    private_key = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 8, "class": "mono", "spellcheck": "false"}),
        label="或粘贴私钥 PEM",
        help_text="未加密的 PKCS#8 或 PKCS#1 PEM，必须与证书匹配。",
    )
    auto_renew = forms.BooleanField(
        required=False,
        label="由 certbot 自动管理",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "选择暂存的证书目录")]
        for directory in _staged_certificate_dirs():
            choices.append((str(directory), f"{directory.name} · {directory}"))
        self.fields["server_certificate"].choices = choices

    def clean(self):
        cleaned = super().clean()
        server = (cleaned.get("server_certificate") or "").strip()
        cert_file = cleaned.get("certificate_file")
        key_file = cleaned.get("private_key_file")

        if server:
            base = Path(server).resolve()
            root = paths.imports_dir().resolve()
            if not base.is_relative_to(root):
                raise forms.ValidationError("证书路径必须位于 Ostium 的 imports 目录。")
            cert_path = base / "fullchain.pem"
            key_path = base / "privkey.pem"
            try:
                cert_pem = cert_path.read_text(encoding="utf-8")
                key_pem = key_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise forms.ValidationError(f"无法读取证书文件：{exc}") from exc
        elif cert_file or key_file:
            if not cert_file or not key_file:
                raise forms.ValidationError("上传证书和私钥必须同时选择。")
            try:
                cert_pem = cert_file.read().decode("utf-8")
                key_pem = key_file.read().decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise forms.ValidationError(f"无法读取上传文件：{exc}") from exc
        else:
            cert_pem = (cleaned.get("certificate") or "").strip()
            key_pem = (cleaned.get("private_key") or "").strip()
            if not cert_pem or not key_pem:
                raise forms.ValidationError("请选择服务器暂存证书、上传文件，或粘贴证书和私钥。")

        try:
            parsed = parse_certificate(cert_pem, key_pem)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages) from exc

        cleaned["domain"] = (cleaned.get("domain") or "").strip() or parsed["domain"]
        if not cleaned["domain"]:
            raise forms.ValidationError("无法从证书中识别域名，请手动填写域名。")
        cleaned["certificate"] = cert_pem
        cleaned["private_key"] = key_pem
        return cleaned
