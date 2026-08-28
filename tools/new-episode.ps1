<#
.SYNOPSIS
    Выпуск канала по шагам: завести — озвучить и раскадровать — собрать.

.DESCRIPTION
    Конвейер обрывается в двух местах, и оба обрыва здесь честно разделены.

    1. Текст. Сценарий пишет человек или сильный ассистент по методике
       канала: досье фактов, script.md, заголовки. Если писать некому,
       ключ -Text отдаёт эту работу настроенной модели: на локальной
       получится черновик под правку, а не готовый текст.
    2. Клипы. Их генерирует Flow вручную по промптам.

    Между ними и после них всё автоматическое:
       -Produce   script.md -> voice.mp3, субтитры, раскадровка
       -Prompts   раскадровка -> библия и промпты Flow силами модели
       -Assemble  clips/ -> video.mp4

.EXAMPLE
    .\new-episode.ps1 -Channel kak-bylo -Topic "Пожар в MGM Grand"
    .\new-episode.ps1 -Channel kak-bylo -Episode "Пожар в MGM Grand" -Produce
    .\new-episode.ps1 -Channel kak-bylo -Episode "Пожар в MGM Grand" -Assemble
    .\new-episode.ps1 -Channel hindi -Topic "The Wells of Rajasthan"
#>
[CmdletBinding()]
param(
    # имя канала (vidpipe channels) или путь к его папке
    [Parameter(Mandatory = $true)][string]$Channel,

    # тема нового выпуска; не нужна для -Produce и -Assemble
    [string]$Topic,

    # папка выпуска: номер или название. По умолчанию — по обычаю канала
    [string]$Episode,

    # написать текст локальной моделью: досье, сценарий, разбор, упаковка
    [switch]$Text,

    # текст готов: озвучка, субтитры, раскадровка
    [switch]$Produce,

    # отдать библию и промпты Flow модели, а не писать их руками
    [switch]$Prompts,

    # клипы готовы: собрать видео
    [switch]$Assemble,

    # перезаписать уже посчитанное
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

# Дочерние процессы пишут по-русски, консоль Windows читает их в своей кодовой
# странице. Без этого пути и сообщения приезжают искажёнными.
$env:PYTHONIOENCODING = 'utf-8'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

# --- каналы -----------------------------------------------------------------
# Список каналов скрипт у себя не держит: его знает vidpipe. Новый язык
# заводится командой `vidpipe init --channel ИМЯ --lang КОД --dir ПУТЬ`
# и появляется здесь сам, без правки этого файла.
$channels = @{}
try {
    $raw = & vidpipe channels --json 2>$null
    if ($LASTEXITCODE -eq 0 -and $raw) {
        (ConvertFrom-Json $raw).PSObject.Properties |
            ForEach-Object { $channels[$_.Name] = $_.Value }
    }
} catch { }

$root = if ($channels.ContainsKey($Channel)) { $channels[$Channel] } else { $Channel }

if (-not (Test-Path -LiteralPath $root)) {
    $известные = if ($channels.Count) { $channels.Keys -join ', ' }
                 else { 'ни одного — проверь CHANNELS_ROOT в ~\.vidpipe\.env' }
    throw "Канал не найден: $root. Известные: $известные"
}
if (-not (Test-Path -LiteralPath (Join-Path $root '.vidpipe-channel'))) {
    throw "В $root нет .vidpipe-channel — это не канал. Создать: vidpipe init --channel ИМЯ --dir `"$root`""
}

# --- имя папки выпуска ------------------------------------------------------
# У каналов разный обычай: где-то выпуски пронумерованы, где-то названы по
# теме. Подстраиваемся под тот, что уже сложился в этом канале.
function Get-EpisodeName($channelRoot, $topic) {
    $numbered = Get-ChildItem -LiteralPath $channelRoot -Directory |
        Where-Object { $_.Name -match '^\d+$' } |
        ForEach-Object { [int]$_.Name }
    if ($numbered) {
        return [string]((($numbered | Measure-Object -Maximum).Maximum + 1))
    }
    $named = Get-ChildItem -LiteralPath $channelRoot -Directory |
        Where-Object { $_.Name -notmatch '^[._]' }
    if ($named -and $topic) {
        $чистое = ($topic -replace '[<>:"/\\|?*]', ' ').Trim()
        $чистое = ($чистое -replace '\s+', ' ')
        if ($чистое.Length -gt 60) { $чистое = $чистое.Substring(0, 60).Trim() }
        return $чистое
    }
    return '1'
}

if (-not $Episode) {
    if ($Assemble -or $Produce) {
        throw "Укажи выпуск: -Episode 3 или -Episode `"Название папки`""
    }
    $Episode = Get-EpisodeName $root $Topic
}

$dir = Join-Path $root $Episode

function Test-Model($where) {
    # Нужна только ключу -Prompts. Остальные шаги обходятся без модели:
    # озвучка, субтитры и сетка сцен это расчёт, а не рассуждение.
    $почему = & python -c "import sys; from vidpipe.config import load_env; load_env(sys.argv[1]); from vidpipe.llm import readiness; m = readiness(); print(m); sys.exit(1 if m else 0)" $where
    if ($LASTEXITCODE -ne 0) { throw "Модель недоступна. $почему" }
}

# --- сборка из готовых клипов -----------------------------------------------
if ($Assemble) {
    $clips = Join-Path $dir 'clips'
    if (-not (Test-Path -LiteralPath $clips)) {
        throw "Нет папки с клипами: $clips. Сложи туда то, что выдал Flow."
    }
    $count = (Get-ChildItem -LiteralPath $clips -File).Count
    Write-Host "=== сборка: $dir ($count файлов в clips) ===" -ForegroundColor Cyan
    $cliArgs = @('run', '--dir', $dir, '-s', 'assemble')
    if ($Force) { $cliArgs += '--force' }
    & vidpipe @cliArgs
    if ($LASTEXITCODE -ne 0) { throw "assemble упал с кодом $LASTEXITCODE" }
    Write-Host "`nготово: $(Join-Path $dir 'video.mp4')" -ForegroundColor Green
    return
}

# --- текст силами модели ----------------------------------------------------
# Запасной путь на случай, когда писать некому: досье, сценарий, разбор и
# упаковка делаются той моделью, что настроена в LLM_PROVIDER. На локальной
# это черновик под правку, а не готовый текст.
if ($Text) {
    $prompt = Join-Path $dir 'prompt.md'
    if (-not (Test-Path -LiteralPath $prompt)) {
        throw "Нет $prompt. Сначала заведи выпуск: -Topic `"тема`""
    }
    Test-Model $dir
    Write-Host "=== текст: $dir ===" -ForegroundColor Cyan
    Write-Host "    методики берутся из канала: research.md, script_engine.md," -ForegroundColor DarkGray
    Write-Host "    review_engine.md, packaging.md" -ForegroundColor DarkGray

    $cliArgs = @('run', '--dir', $dir, '-s', 'research,script,review,thumb')
    if ($Force) { $cliArgs += '--force' }
    & vidpipe @cliArgs
    if ($LASTEXITCODE -ne 0) { throw "текстовые шаги упали с кодом $LASTEXITCODE" }

    Write-Host "`n--- вычитай перед озвучкой ---" -ForegroundColor Yellow
    Write-Host "  досье:     $(Join-Path $dir 'dossier.md')  даты и цифры сверь по источникам"
    Write-Host "  сценарий:  $(Join-Path $dir 'script.md')"
    Write-Host "  упаковка:  $(Join-Path $dir 'thumbnail.txt')"
    Write-Host "`n  потом: -Channel $Channel -Episode `"$Episode`" -Produce"
    return
}

# --- текст готов: всё остальное автоматически -------------------------------
if ($Produce) {
    $script = Join-Path $dir 'script.md'
    if (-not (Test-Path -LiteralPath $script)) {
        throw "Нет $script. Сценарий пишется по методике канала, скрипт его не сочиняет."
    }
    Write-Host "=== производство: $dir ===" -ForegroundColor Cyan

    # Что сюда не входит и почему.
    # script и review: текст уже написан человеком, переписывать его нельзя.
    # bible и flow: это решения, а не механика. Локальная модель на них
    # ошибается дорого, а проверять её выходит дольше, чем написать самому.
    # Нужны они всё же от модели, есть отдельный ключ -Prompts.
    $cliArgs = @('run', '--dir', $dir, '-s', 'clean,tts,srt,shotlist')
    if ($Force) { $cliArgs += '--force' }
    & vidpipe @cliArgs
    if ($LASTEXITCODE -ne 0) { throw "конвейер упал с кодом $LASTEXITCODE" }

    Write-Host "`n--- дальше ---" -ForegroundColor Yellow
    Write-Host "  раскадровка:  $(Join-Path $dir 'shotlist.csv')"
    Write-Host "  по ней пишутся библия героев и промпты для Flow."
    Write-Host "  отдать это модели: тот же вызов с ключом -Prompts"
    Write-Host "  потом клипы в $(Join-Path $dir 'clips') и ключ -Assemble"
    return
}

# --- библия и промпты силами модели -----------------------------------------
if ($Prompts) {
    if (-not (Test-Path -LiteralPath (Join-Path $dir 'shotlist.csv'))) {
        throw "Нет раскадровки. Сначала: -Channel $Channel -Episode `"$Episode`" -Produce"
    }
    Test-Model $dir
    Write-Host "=== библия и промпты: $dir ===" -ForegroundColor Cyan
    Write-Host "    модель ошибается на этом шаге дорого, вычитывай результат" -ForegroundColor DarkGray

    $cliArgs = @('run', '--dir', $dir, '-s', 'bible,flow')
    if ($Force) { $cliArgs += '--force' }
    & vidpipe @cliArgs
    if ($LASTEXITCODE -ne 0) { throw "шаг упал с кодом $LASTEXITCODE" }
    Write-Host "`n  проверь: $(Join-Path $dir 'bible.md') и $(Join-Path $dir 'flow_prompts.md')"
    return
}

# --- завести выпуск ---------------------------------------------------------
if (-not $Topic) { throw "Нужна тема: -Topic `"...`"" }

if ((Test-Path -LiteralPath $dir) -and -not $Force) {
    $busy = Get-ChildItem -LiteralPath $dir -File -ErrorAction SilentlyContinue
    if ($busy) {
        throw "Папка $dir уже не пуста. Возьми другой -Episode или добавь -Force."
    }
}

New-Item -ItemType Directory -Path $dir -Force | Out-Null
Write-Host "=== канал $Channel, выпуск «$Episode» ===" -ForegroundColor Cyan
Write-Host "    $dir"

& vidpipe init --dir $dir --topic $Topic
if ($LASTEXITCODE -ne 0) { throw "init упал с кодом $LASTEXITCODE" }

$канал = Join-Path $root '.vidpipe-channel'
Write-Host "`n--- дальше текст ---" -ForegroundColor Yellow
Write-Host "  1. ТЗ:        $(Join-Path $dir 'prompt.md')  — дополни фактами и ограничениями"
Write-Host "  2. досье:     $(Join-Path $dir 'dossier.md')  по $(Join-Path $канал 'research.md')"
Write-Host "  3. сценарий:  $(Join-Path $dir 'script.md')   по $(Join-Path $канал 'script_engine.md')"
Write-Host "  4. упаковка:  $(Join-Path $dir 'thumbnail.txt') по $(Join-Path $канал 'packaging.md')"
Write-Host "`n  когда script.md готов:" -ForegroundColor Yellow
Write-Host "  .\new-episode.ps1 -Channel $Channel -Episode `"$Episode`" -Produce"
