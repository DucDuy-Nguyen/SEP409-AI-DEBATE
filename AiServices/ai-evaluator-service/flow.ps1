# Test tay toan bo luong: evaluate -> coaching -> round x3 -> coaching round -> session
# Chay: powershell -ExecutionPolicy Bypass -File flow.ps1   (server phai dang chay o :8000)

$base = "http://localhost:8000"

function Post($path, $obj) {
    $json = $obj | ConvertTo-Json -Depth 10
    $params = @{
        Method      = "Post"
        Uri         = "$base$path"
        Body        = [Text.Encoding]::UTF8.GetBytes($json)
        ContentType = "application/json; charset=utf-8"
    }
    Invoke-RestMethod @params
}

function Names($items) {
    ($items | ForEach-Object { "$($_.name)($($_.current_score))" }) -join ", "
}

$motion = "THBT mang xa hoi gay hai nhieu hon loi"

# --- 1. Cham 1 luot noi -> goi y ---
$argText = "Mang xa hoi lam giam thoi gian tuong tac truc tiep, " +
           "dan den suy giam ky nang giao tiep o gioi tre."
$arg = @{
    motion                 = $motion
    side                   = "pro"
    stage                  = "rebuttal"
    argument_text          = $argText
    opponent_argument_text = "Mang xa hoi giup ket noi nguoi o xa nhau."
}
$ev = Post "/evaluate" $arg
"ARGUMENT overall_score = $($ev.overall_score)"

$co = Post "/coaching/argument" @{ request = $arg; evaluation = $ev }
"COACHING argument focus = " + (Names $co.focus_criteria)

# --- 2. Cham tung round -> goi y round ---
$opening = @{
    motion = $motion; side = "pro"; stage = "opening"
    turns  = @(
        @{ speaker = "learner"; text = "Mang xa hoi khong tot. No lam nguoi ta buon." }
    )
}
$rebuttal = @{
    motion = $motion; side = "pro"; stage = "rebuttal"
    turns  = @(
        @{ speaker = "opponent"; text = "Mang xa hoi giup ket noi nguoi o xa nhau." },
        @{ speaker = "learner"; text = "Ket noi so luong khong dong nghia chat luong." }
    )
}
$closing = @{
    motion = $motion; side = "pro"; stage = "closing"
    turns  = @(
        @{ speaker = "learner"; text = "Tom lai, mang xa hoi lam suy giam ket noi that." }
    )
}

$roundResults = @()
foreach ($r in @($opening, $rebuttal, $closing)) {
    $rev = Post "/evaluate/round" $r
    $rco = Post "/coaching/round" @{ request = $r; evaluation = $rev }
    "ROUND $($r.stage) round_score = $($rev.round_score)"
    "    coaching focus = " + (Names $rco.focus_criteria)
    $roundResults += $rev
}

# --- 3. Bao cao ca phien ---
$sessionBody = @{ motion = $motion; side = "pro"; rounds = $roundResults }
$session = Post "/evaluate/session" $sessionBody
"SESSION overall_score = $($session.overall_score)"
"    breakdown = " + ($session.stage_breakdown | ConvertTo-Json -Compress)

# Muon xem chi tiet 1 buoc, bo comment dong tuong ung:
# $co | ConvertTo-Json -Depth 10
# $session | ConvertTo-Json -Depth 10
