<#
.SYNOPSIS
    Один выпуск от темы до промптов Flow — одной командой.

.DESCRIPTION
    Создаёт папку следующего выпуска в нужном канале и прогоняет конвейер до
    промптов Flow. Клипы генерируются в Flow руками — это единственное место,
    где конвейер обрывается. Когда клипы сложены в <выпуск>\clips, добери
    последний шаг: тот же скрипт с -Assemble.

.EXAMPLE
    .\new-episode.ps1 -Channel ru -Topic "Оборона Киева 1941"
    .\new-episode.ps1 -Channel hindi -Topic "The Wells of Rajasthan" -Edit
    .\new-episode.ps1 -Channel ru -Episode 3 -Assemble
#>
[CmdletBinding()]
param(
    # ru | hindi | путь к папке канала
    [Parameter(Mandatory = $true)][string]$Channel,

    # тема выпуска; не нужна при -Assemble
    [string]$Topic,

    # номер выпуска: по умолчанию следующий свободный, для -Assemble — обязателен
    [string]$Episode,

    # открыть prompt.md и дождаться правок, прежде чем звать Claude
    [switch]$Edit,

    # только собрать видео из готовых клипов
    [switch]$Assemble,

    # перезаписать уже посчитанные файлы выпуска
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

# --- каналы -----------------------------------------------------------------
# Добавляешь канал — добавь строку сюда, остальное подхватится само.
$CHANNELS = @{
    'ru'    = 'G:\Русский канал'
    'hindi' = 'G:\Новая История'
}

$root = if ($CHANNELS.ContainsKey($Channel)) { $CHANNELS[$Channel] } else { $Channel }

if (-not (Test-Path -LiteralPath $root)) {
    throw "Канал не найден: $root. Известные: $($CHANNELS.Keys -join ', ')"
}
if (-not (Test-Path -LiteralPath (Join-Path $root '.vidpipe-channel'))) {
    throw "В $root нет .vidpipe-channel — это не канал. Создать: vidpipe init --channel ИМЯ --dir `"$root`""
}

# --- номер выпуска ----------------------------------------------------------
function Get-NextEpisode($channelRoot) {
    $numbers = Get-ChildItem -LiteralPath $channelRoot -Directory |
        Where-Object { $_.Name -match '^\d+$' } |
        ForEach-Object { [int]$_.Name }
    if ($numbers) { (($numbers | Measure-Object -Maximum).Maximum + 1) } else { 1 }
}

if (-not $Episode) {
    if ($Assemble) { throw "Для -Assemble укажи номер: -Episode 3" }
    $Episode = Get-NextEpisode $root
}

$dir = Join-Path $root $Episode

# --- сборка из готовых клипов -----------------------------------------------
if ($Assemble) {
    $clips = Join-Path $dir 'clips'
    if (-not (Test-Path -LiteralPath $clips)) {
        throw "Нет папки с клипами: $clips. Сложи туда то, что выдал Flow."
    }
    $count = (Get-ChildItem -LiteralPath $clips -File).Count
    Write-Host "=== сборка: $dir ($count файлов в clips) ===" -ForegroundColor Cyan
    $steps = if ($Force) { @('run', '--dir', $dir, '-s', 'assemble', '--force') }
             else        { @('run', '--dir', $dir, '-s', 'assemble') }
    & vidpipe @steps
    if ($LASTEXITCODE -ne 0) { throw "assemble упал с кодом $LASTEXITCODE" }
    Write-Host "`nготово: $(Join-Path $dir 'video.mp4')" -ForegroundColor Green
    return
}

# --- новый выпуск -----------------------------------------------------------
if (-not $Topic) { throw "Нужна тема: -Topic `"...`"" }

# Ключ проверяем до создания папки: упавший на первом шаге запуск иначе
# оставляет пустую папку и съедает номер выпуска.
& python -c "import sys; from vidpipe.config import load_env, env; load_env(sys.argv[1]); sys.exit(0 if env('ANTHROPIC_API_KEY') else 1)" $root
if ($LASTEXITCODE -ne 0) {
    throw "Не задан ANTHROPIC_API_KEY — шаги script/review/shotlist/flow/thumb без него не пойдут. Впиши его в глобальный .env: notepad `$env:USERPROFILE\.vidpipe\.env"
}

if ((Test-Path -LiteralPath $dir) -and -not $Force) {
    $busy = Get-ChildItem -LiteralPath $dir -File -ErrorAction SilentlyContinue
    if ($busy) {
        throw "Папка $dir уже не пуста. Возьми другой -Episode или добавь -Force."
    }
}

New-Item -ItemType Directory -Path $dir -Force | Out-Null
Write-Host "=== канал $Channel, выпуск $Episode ===" -ForegroundColor Cyan
Write-Host "    $dir"

# ТЗ отдельным шагом: так его можно вычитать до того, как Claude потратит токены
& vidpipe init --dir $dir --topic $Topic
if ($LASTEXITCODE -ne 0) { throw "init упал с кодом $LASTEXITCODE" }

if ($Edit) {
    $prompt = Join-Path $dir 'prompt.md'
    Write-Host "`nправь ТЗ, потом вернись сюда: $prompt" -ForegroundColor Yellow
    Start-Process notepad $prompt -Wait
}

# Клипов ещё нет, поэтому assemble в список не входит — он идёт вторым заходом.
$steps = 'script,review,clean,tts,srt,shotlist,flow,thumb'
$cliArgs = @('run', '--dir', $dir, '-s', $steps)
if ($Force) { $cliArgs += '--force' }

& vidpipe @cliArgs
if ($LASTEXITCODE -ne 0) { throw "конвейер упал с кодом $LASTEXITCODE" }

Write-Host "`n--- дальше руками ---" -ForegroundColor Yellow
Write-Host "  1. промпты для Flow:  $(Join-Path $dir 'flow_prompts.json')"
Write-Host "  2. клипы сложи в:     $(Join-Path $dir 'clips')"
Write-Host "  3. потом собери:      .\new-episode.ps1 -Channel $Channel -Episode $Episode -Assemble"
Write-Host "`n  что вышло по тексту: vidpipe doctor --dir `"$dir`""
