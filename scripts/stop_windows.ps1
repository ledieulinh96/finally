# Stop and remove the FinAlly container (Windows PowerShell). Keeps the finally-data volume. Idempotent.
$Container = "finally"
docker container inspect $Container *> $null
if ($LASTEXITCODE -eq 0) {
    docker rm -f $Container | Out-Null
    Write-Host "FinAlly stopped. Data kept in volume 'finally-data' (remove with: docker volume rm finally-data)."
} else {
    Write-Host "FinAlly is not running."
}
