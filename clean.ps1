# Remove apenas arquivos de trabalho gerados durante testes e compilacao.
# Preserva executaveis, relatorios, bancos de dados, codigo e configuracoes.
[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$projectPrefix = $projectRoot.TrimEnd('\') + '\'

function Remove-GeneratedItem {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $item = Get-Item -LiteralPath $Path -Force
    $resolvedPath = [IO.Path]::GetFullPath($item.FullName)
    if (-not $resolvedPath.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Caminho fora da pasta do projeto: $resolvedPath"
    }
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        Write-Warning "Atalho preservado: $resolvedPath"
        return
    }
    if ($PSCmdlet.ShouldProcess($resolvedPath, 'Remover arquivo gerado')) {
        try {
            Remove-Item -LiteralPath $resolvedPath -Recurse -Force -ErrorAction Stop
            Write-Host "Removido: $resolvedPath"
        } catch {
            Write-Warning "Nao foi possivel remover: $resolvedPath. $($_.Exception.Message)"
        }
    }
}

foreach ($relativePath in @('build', '__pycache__', 'tests\__pycache__')) {
    Remove-GeneratedItem (Join-Path $projectRoot $relativePath)
}
$temporaryPath = Join-Path $projectRoot 'temp'
if (Test-Path -LiteralPath $temporaryPath) {
    # Pastas _MEI podem pertencer ao programa em execucao.
    Get-ChildItem -LiteralPath $temporaryPath -Force |
        Where-Object { $_.Name -notlike '_MEI*' } |
        ForEach-Object { Remove-GeneratedItem $_.FullName }
}
Write-Host 'Limpeza concluida. Dados e executaveis foram preservados.'
