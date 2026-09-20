# Private SAPI host. Never loaded inside either application's GUI process.
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$wardogsSpeech = $null
while ($null -ne ($wardogsLine = [Console]::ReadLine())) {
    try {
        $request = $wardogsLine | ConvertFrom-Json
        if ($request.op -ne 'voices' -and $request.op -ne 'speak') { throw 'Unknown speech operation' }
        if ($null -eq $wardogsSpeech) { $wardogsSpeech = New-Object -ComObject SAPI.SpVoice }
        $voices = @($wardogsSpeech.GetVoices() | ForEach-Object {
            try {
                $language = [Globalization.CultureInfo]::GetCultureInfo([Convert]::ToInt32($_.GetAttribute('Language').Split(';')[0],16)).Name
                $name = $_.GetAttribute('Name')
                if (-not $name) { $name = $_.GetDescription() }
                @{name=$name; description=$_.GetDescription(); language=$language; token=$_}
            } catch { } # One broken token must not hide the remaining voices.
        })
        if ($request.op -eq 'voices') {
            $result = @{ok=$true; voices=@($voices | ForEach-Object { @{name=$_.name; description=$_.description; language=$_.language} })}
        } else {
            $prefix = ([string]$request.language).Split('-')[0]
            $voice = $voices | Where-Object { ($_.name -eq $request.voice -or $_.description -eq $request.voice) -and $_.language -like ($prefix + '*') } | Select-Object -First 1
            if ($null -eq $voice) { $voice = $voices | Where-Object { $_.language -like ($prefix + '*') } | Select-Object -First 1 }
            if ($null -eq $voice) { throw ('No installed voice for ' + $request.language) }
            $wardogsSpeech.Voice = $voice.token
            $wardogsSpeech.Rate = [Math]::Max(-10, [Math]::Min(10, [int]$request.rate))
            $stream = New-Object -ComObject SAPI.SpFileStream
            $stream.Open([string]$request.path, 3, $false)
            try {
                $wardogsSpeech.AudioOutputStream = $stream
                $null = $wardogsSpeech.Speak([string]$request.text, 16)
            } finally { $stream.Close(); $wardogsSpeech.AudioOutputStream = $null }
            $result = @{ok=$true; path=$request.path; voice=$voice.name}
        }
    } catch { $result = @{ok=$false; error=$_.Exception.Message} }
    [Console]::WriteLine(($result | ConvertTo-Json -Compress -Depth 5))
}
