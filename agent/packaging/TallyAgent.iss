; Tally Analytics Sync Agent installer (P16.8, D-042 #3, D-043 #3/#4).
;
; Compiled on windows-latest in CI by .github/workflows/agent-build.yml, so the installer is
; built and smoke-tested on every Agent build even though it cannot be *installed* there.
;
;   iscc /DAppVersion=0.1.0 /DSourceDir=..\..\dist\TallyAgent TallyAgent.iss
;
; Signing (P16.8a) is deliberately NOT configured here: it needs an EV Authenticode certificate
; whose key lives in a hardware token or cloud HSM, which the project does not have yet. When it
; does, add SignTool to this file - do not sign by hand, or an unsigned build will ship one day.
; Until then SmartScreen will warn, and docs/agent-install.md says so plainly.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\TallyAgent"
#endif

#define AppName "Tally Analytics Sync Agent"
#define ServiceName "TallyAgent"
#define ServiceAccount "NT SERVICE\TallyAgent"

[Setup]
AppId={{8F3C2A74-5D21-4E8B-9C6F-7A1B0D4E5F62}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Tally Analytics
DefaultDirName={autopf}\TallyAgent
DefaultGroupName=Tally Analytics
DisableDirPage=auto
DisableProgramGroupPage=yes
OutputBaseFilename=TallyAgent-Setup-{#AppVersion}
OutputDir=.
Compression=lzma2
SolidCompression=yes
; x64 only: the Agent is a 64-bit PyInstaller build and must run on real x64 hardware (D-043 #3).
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The service, Program Files and the ACLs all need it.
PrivilegesRequired=admin
WizardStyle=modern
LicenseFile={#SourceDir}\agent-install.md
UninstallDisplayName={#AppName}

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; AGT-2.6: the data folder holds the queue, the logs and the DPAPI-encrypted credential. Only
; the service account, SYSTEM and Administrators may read it - inheritance is broken so the
; machine's default "Users: read" does not apply.
Name: "{commonappdata}\TallyAgent"; Permissions: everyone-none

[Icons]
Name: "{group}\Tally Agent installation guide"; Filename: "{app}\agent-install.md"

[Run]
; 1. Lock the data folder down. Done with icacls rather than [Dirs] Permissions alone, because
;    the virtual service account is not an identity Inno can name.
Filename: "{sys}\icacls.exe"; \
  Parameters: """{commonappdata}\TallyAgent"" /inheritance:r /grant:r ""{#ServiceAccount}:(OI)(CI)F"" ""*S-1-5-18:(OI)(CI)F"" ""*S-1-5-32-544:(OI)(CI)F"""; \
  StatusMsg: "Restricting the data folder to the service account"; Flags: runhidden

; 2. Register with the backend, from what the wizard collected. Skipped on an upgrade, where a
;    configuration and credential already exist - re-registering would issue a second Agent.
Filename: "{app}\tally-agent.exe"; \
  Parameters: "register --token ""{code:GetToken}"" --name ""{code:GetAgentName}"" --backend-url ""{code:GetBackendUrl}"" --company ""{code:GetCompany}"" --tally-host ""{code:GetTallyHost}"" --tally-port {code:GetTallyPort}"; \
  StatusMsg: "Registering this Agent with the backend"; \
  Flags: runhidden; Check: ShouldRegister

; 3. Create the service, as a low-privilege virtual account rather than LocalSystem, starting
;    with Windows but delayed so TallyPrime and the network are up first.
Filename: "{sys}\sc.exe"; \
  Parameters: "create {#ServiceName} binPath= ""\""{app}\tally-agent-service.exe\"""" obj= ""{#ServiceAccount}"" start= delayed-auto DisplayName= ""{#AppName}"""; \
  StatusMsg: "Creating the Windows service"; Flags: runhidden; Check: ServiceMissing
Filename: "{sys}\sc.exe"; \
  Parameters: "description {#ServiceName} ""Reads TallyPrime (read-only) and uploads to Tally Analytics over HTTPS."""; \
  Flags: runhidden; Check: ServiceMissing
; Restart on failure: twice after a minute, then every five. An Agent that dies at 2am should be
; running again by morning without anyone visiting the machine.
Filename: "{sys}\sc.exe"; \
  Parameters: "failure {#ServiceName} reset= 86400 actions= restart/60000/restart/60000/restart/300000"; \
  Flags: runhidden; Check: ServiceMissing
Filename: "{sys}\sc.exe"; Parameters: "start {#ServiceName}"; \
  StatusMsg: "Starting the service"; Flags: runhidden

[UninstallRun]
; D-043 #4: the service goes, the program files go, the DATA folder stays. The queue and the
; logs are what someone needs in order to find out why the Agent was removed, and the encrypted
; credential is useless once revoked in the dashboard - which the uninstaller says to do.
Filename: "{sys}\sc.exe"; Parameters: "stop {#ServiceName}"; Flags: runhidden; RunOnceId: "StopService"
Filename: "{sys}\sc.exe"; Parameters: "delete {#ServiceName}"; Flags: runhidden; RunOnceId: "DeleteService"

[Code]
var
  WizardPage: TInputQueryWizardPage;
  TallyPage: TInputQueryWizardPage;
  AlreadyConfigured: Boolean;

function ConfigPath(): String;
begin
  Result := ExpandConstant('{commonappdata}\TallyAgent\agent.toml');
end;

{ An upgrade must keep the configuration, the credential and the queue (P16.8). If a
  configuration is already there, this is an upgrade: do not ask again and do not re-register,
  which would issue a second Agent for the same machine. }
function IsUpgrade(): Boolean;
begin
  Result := FileExists(ConfigPath());
end;

procedure InitializeWizard();
begin
  AlreadyConfigured := IsUpgrade();

  WizardPage := CreateInputQueryPage(wpSelectDir,
    'Connect this Agent', 'Where the Agent uploads to, and what to call it.',
    'The registration token comes from the dashboard: Agents > Generate registration token.' +
    ' It can be used once.');
  WizardPage.Add('Backend URL (https://...):', False);
  WizardPage.Add('A name for this Agent (e.g. Head Office):', False);
  WizardPage.Add('Registration token:', True);

  TallyPage := CreateInputQueryPage(WizardPage.ID,
    'TallyPrime on this PC', 'Where TallyPrime is, and which company to read.',
    'The company name must match Tally exactly. Leave the host and port alone unless Tally''s' +
    ' XML server has been moved.');
  TallyPage.Add('Tally company name:', False);
  TallyPage.Add('Tally host:', False);
  TallyPage.Add('Tally port:', False);

  TallyPage.Values[1] := 'localhost';
  TallyPage.Values[2] := '9000';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { On an upgrade there is nothing to ask. }
  Result := AlreadyConfigured and ((PageID = WizardPage.ID) or (PageID = TallyPage.ID));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Port: Integer;
begin
  Result := True;
  if AlreadyConfigured then
    Exit;

  if CurPageID = WizardPage.ID then
  begin
    { https only: the Agent refuses plain http to anything but localhost anyway (SEC-2.0), and
      finding that out after the install is a bad first experience. }
    if Pos('https://', Lowercase(Trim(WizardPage.Values[0]))) <> 1 then
    begin
      MsgBox('The backend URL must begin with https://', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if Trim(WizardPage.Values[1]) = '' then
    begin
      MsgBox('Please give this Agent a name, so it can be told apart in the dashboard.',
        mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if Trim(WizardPage.Values[2]) = '' then
    begin
      MsgBox('The registration token is needed to connect this Agent.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end
  else if CurPageID = TallyPage.ID then
  begin
    if Trim(TallyPage.Values[0]) = '' then
    begin
      MsgBox('The Tally company name is needed, exactly as it appears in Tally.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    Port := StrToIntDef(Trim(TallyPage.Values[2]), -1);
    if (Port < 1) or (Port > 65535) then
    begin
      MsgBox('The Tally port must be a number between 1 and 65535 (usually 9000).',
        mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;
end;

function ShouldRegister(): Boolean;
begin
  Result := not AlreadyConfigured;
end;

function ServiceMissing(): Boolean;
var
  ResultCode: Integer;
begin
  { sc.exe query returns 1060 when the service does not exist. On an upgrade the service is
    already there and must not be created again. }
  Exec(ExpandConstant('{sys}\sc.exe'), 'query {#ServiceName}', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode);
  Result := ResultCode <> 0;
end;

function GetBackendUrl(Param: String): String;
begin
  Result := Trim(WizardPage.Values[0]);
end;

function GetAgentName(Param: String): String;
begin
  Result := Trim(WizardPage.Values[1]);
end;

function GetToken(Param: String): String;
begin
  Result := Trim(WizardPage.Values[2]);
end;

function GetCompany(Param: String): String;
begin
  Result := Trim(TallyPage.Values[0]);
end;

function GetTallyHost(Param: String): String;
begin
  Result := Trim(TallyPage.Values[1]);
end;

function GetTallyPort(Param: String): String;
begin
  Result := Trim(TallyPage.Values[2]);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  { Stop the service before overwriting its executables on an upgrade; [Files] cannot replace a
    running binary. The queue and the credential live in the data folder and are untouched. }
  if (CurStep = ssInstall) and AlreadyConfigured then
    Exec(ExpandConstant('{sys}\sc.exe'), 'stop {#ServiceName}', '', SW_HIDE,
      ewWaitUntilTerminated, ResultCode);
end;
