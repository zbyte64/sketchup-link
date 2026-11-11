# Simple one-liner to test: Test the Samba share access
Write-Output "Shared folder test"
$testPath = "$env:USERPROFILE\Desktop\Shared"
if (Test-Path $testPath) {
    Write-Output "Shared folder exists: $testPath"
    Get-ChildItem $testPath -Depth 1 -Name | ForEach-Object { Write-Output "  $_" }
} else {
    Write-Output "Shared folder NOT found: $testPath"
    # Try alternate paths
    $altPaths = @(
        "\\host.lan\Data",
        "\\20.20.20.1\Data",
        "$env:USERPROFILE\Desktop\Shared.lnk"
    )
    foreach ($p in $altPaths) {
        if (Test-Path $p) {
            Write-Output "Alternate path found: $p"
        } else {
            Write-Output "Not found: $p"
        }
    }
}
