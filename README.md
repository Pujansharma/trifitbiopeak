# trifitbiopeak






$token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzkxOTYzMDMwLCJpYXQiOjE3OTE4NzY2MzAsImp0aSI6IjZjODdkODk1OTdjMjRjNTJiOGQ4ZWI0ZWM5MTUwM2I5IiwiaWQiOiIwMWExMzM4ZC0wMGY5LTcwMDctOTc2OS1mOWUyZTAzZDk4ZWIiLCJlbWFpbCI6ImJpb3BlYWsudGVzdDFAZXhhbXBsZS5pbnZhbGlkIiwicGhvbmUiOiIrOTEtOTAwMDAwMDAwMSIsInVzZXJfdHlwZSI6InVua25vd24ifQ.FDT"
$payload = $token.Split('.')[1].Replace('-', '+').Replace('_', '/')
switch ($payload.Length % 4) {
    2 { $payload += '==' }
    3 { $payload += '=' }
}
[System.Text.Encoding]::UTF8.GetString(
    [System.Convert]::FromBase64String($payload)
)