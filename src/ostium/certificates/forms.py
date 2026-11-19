"""Certificate import form shared by the console and Django admin."""

from __future__ import annotations

from django import forms


class CertificateImportForm(forms.Form):
    domain = forms.CharField(
        max_length=253,
        label="域名",
        help_text="证书的 SAN 或 CN 必须包含这个域名。",
    )
    certificate = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 8, "class": "mono", "spellcheck": "false"}),
        label="证书 PEM",
        help_text="粘贴完整证书链，包含站点证书。",
    )
    private_key = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 8, "class": "mono", "spellcheck": "false"}),
        label="私钥 PEM",
        help_text="未加密的 PKCS#8 或 PKCS#1 PEM，必须与证书匹配。",
    )
    auto_renew = forms.BooleanField(
        required=False,
        label="由 certbot 自动管理",
    )
