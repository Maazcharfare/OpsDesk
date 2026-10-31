[CmdletBinding()]
param(
    [switch]$TrustCertificate
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$certificateDirectory = Join-Path $projectRoot 'deploy\certs'
New-Item -ItemType Directory -Path $certificateDirectory -Force | Out-Null

$certificate = Get-ChildItem Cert:\CurrentUser\My |
    Where-Object {
        $_.Subject -eq 'CN=localhost' -and
        $_.FriendlyName -eq 'OpsDesk local HTTPS' -and
        $_.HasPrivateKey -and
        $_.NotAfter -gt (Get-Date)
    } |
    Sort-Object NotAfter -Descending |
    Select-Object -First 1

if (-not $certificate) {
    $certificate = New-SelfSignedCertificate `
        -Subject 'CN=localhost' `
        -TextExtension @('2.5.29.17={text}DNS=localhost&IPAddress=127.0.0.1') `
        -Type SSLServerAuthentication `
        -CertStoreLocation Cert:\CurrentUser\My `
        -FriendlyName 'OpsDesk local HTTPS' `
        -KeyAlgorithm RSA `
        -KeyLength 2048 `
        -HashAlgorithm SHA256 `
        -KeyExportPolicy Exportable `
        -NotAfter (Get-Date).AddMonths(12)
}

$privateKey = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($certificate)
if (-not $privateKey) {
    throw 'The local TLS certificate does not have an RSA private key.'
}

$certificatePath = Join-Path $certificateDirectory 'fullchain.pem'
$privateKeyPath = Join-Path $certificateDirectory 'privkey.pem'
$publicCertificatePath = Join-Path $certificateDirectory 'localhost.cer'
$utf8 = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($certificatePath, $certificate.ExportCertificatePem(), $utf8)
[System.IO.File]::WriteAllText($privateKeyPath, $privateKey.ExportPkcs8PrivateKeyPem(), $utf8)
Export-Certificate -Cert $certificate -FilePath $publicCertificatePath -Force | Out-Null

$keyAcl = Get-Acl -LiteralPath $privateKeyPath
$keyAcl.SetAccessRuleProtection($true, $false)
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$readRule = [System.Security.AccessControl.FileSystemAccessRule]::new(
    $currentUser,
    [System.Security.AccessControl.FileSystemRights]::Read,
    [System.Security.AccessControl.AccessControlType]::Allow
)
$keyAcl.SetAccessRule($readRule)
Set-Acl -LiteralPath $privateKeyPath -AclObject $keyAcl

if ($TrustCertificate) {
    $alreadyTrusted = Get-ChildItem Cert:\CurrentUser\Root |
        Where-Object Thumbprint -eq $certificate.Thumbprint |
        Select-Object -First 1
    if (-not $alreadyTrusted) {
        Import-Certificate -FilePath $publicCertificatePath -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
    }
    Write-Output 'Trusted this localhost-only certificate in the current Windows user profile.'
} else {
    Write-Output 'Certificate created but not added to the Windows trust store. Chrome will show a certificate warning until it is trusted.'
}

Write-Output "Certificate files: $certificateDirectory"
Write-Output 'Open https://127.0.0.1:8443 after starting compose.local.yaml.'
