param(
    [ValidateSet('Lock', 'Metadata', 'Build', 'Test')]
    [string]$Mode = 'Test'
)

$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$dev = Join-Path $root '.dev'
$rust = Join-Path $dev 'toolchain-components/rustc-1.99.0-x86_64-pc-windows-msvc/rustc/bin'
$cargo = Join-Path $dev 'toolchain-components/cargo-1.99.0-x86_64-pc-windows-msvc/cargo/bin/cargo.exe'
$msvc = 'E:/VSBuildTools/VC/Tools/MSVC/14.44.35207'
$sdk = 'C:/Program Files (x86)/Windows Kits/10'
$sdkVersion = '10.0.28000.0'
$native = Join-Path $dev 'sqlite-native'
$source = Join-Path $dev 'sqlite-source'
$target = Join-Path $dev 'runtime-target'
$settings = @{
    CARGO_HOME = (Join-Path $dev 'cargo-home')
    CARGO_TARGET_DIR = $target
    RUSTC = (Join-Path $rust 'rustc.exe')
    RUSTDOC = (Join-Path $rust 'rustdoc.exe')
    RUSTC_WRAPPER = ''
    RUSTC_WORKSPACE_WRAPPER = ''
    RUSTC_BOOTSTRAP = ''
    RUSTFLAGS = ''
    CARGO_ENCODED_RUSTFLAGS = ''
    SQLITE3_LIB_DIR = $native
    SQLITE3_INCLUDE_DIR = $source
    SQLITE3_STATIC = '1'
    LIBSQLITE3_SYS_USE_PKG_CONFIG = '0'
    PKG_CONFIG = (Join-Path $dev 'no-pkg-config.exe')
    PATH = "$msvc/bin/Hostx64/x64;$rust;$env:PATH"
    LIB = "$msvc/lib/x64;$sdk/Lib/$sdkVersion/ucrt/x64;$sdk/Lib/$sdkVersion/um/x64"
    INCLUDE = "$msvc/include;$sdk/Include/$sdkVersion/ucrt;$sdk/Include/$sdkVersion/shared;$sdk/Include/$sdkVersion/um"
}
$before = @{}
foreach ($key in $settings.Keys) {
    $before[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
    [Environment]::SetEnvironmentVariable($key, $settings[$key], 'Process')
}
try {
    Push-Location -LiteralPath $root
    if ($Mode -eq 'Lock') {
        & $cargo generate-lockfile --offline
        if ($LASTEXITCODE -ne 0) { throw 'Official Cargo lock generation failed' }
    } elseif ($Mode -eq 'Metadata') {
        & $cargo metadata --format-version 1 --locked --offline --filter-platform x86_64-pc-windows-msvc
        if ($LASTEXITCODE -ne 0) { throw 'Official Cargo metadata failed' }
    } else {
        if (-not (Test-Path -LiteralPath $native)) { New-Item -ItemType Directory -Path $native | Out-Null }
        $resolvedNative = [IO.Path]::GetFullPath($native)
        if (-not $resolvedNative.StartsWith([IO.Path]::GetFullPath($dev) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Native output outside .dev' }
        $sourceHash = (Get-FileHash -LiteralPath (Join-Path $source 'sqlite3.c') -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($sourceHash -ne 'b1dd5d74ec7f29055a6684fa06fb3c2f6821c87dd38f9a458dfd2e8a1db28189') { throw 'SQLite source hash drift' }
        $object = Join-Path $native 'sqlite3.obj'
        $library = Join-Path $native 'sqlite3.lib'
        if (-not (Test-Path -LiteralPath $library)) {
            & "$msvc/bin/Hostx64/x64/cl.exe" /nologo /c /O2 /MD /W3 /DSQLITE_THREADSAFE=1 /DSQLITE_DEFAULT_FOREIGN_KEYS=1 /DSQLITE_ENABLE_API_ARMOR /DSQLITE_OMIT_LOAD_EXTENSION "/Fo$object" (Join-Path $source 'sqlite3.c')
            if ($LASTEXITCODE -ne 0) { throw 'Isolated SQLite compilation failed' }
            & "$msvc/bin/Hostx64/x64/lib.exe" /nologo "/OUT:$library" $object
            if ($LASTEXITCODE -ne 0) { throw 'Isolated SQLite archive failed' }
        }
        if ($Mode -eq 'Test') {
            & $cargo test --frozen --offline
        } else {
            & $cargo build --frozen --offline
        }
        if ($LASTEXITCODE -ne 0) { throw "Core $Mode failed" }
    }
} finally {
    Pop-Location
    foreach ($key in $settings.Keys) { [Environment]::SetEnvironmentVariable($key, $before[$key], 'Process') }
}
