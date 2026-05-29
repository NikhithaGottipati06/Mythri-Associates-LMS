[Setup]
AppName=Sharp Associates LMS
AppVersion=1.0
AppPublisher=Sharp Associates
AppPublisherURL=
AppSupportURL=
DefaultDirName={localappdata}\Programs\SharpLMS
DefaultGroupName=Sharp Associates LMS
OutputDir=Output
OutputBaseFilename=SharpLMS_Setup
SetupIconFile=sharp_lms.ico
WizardStyle=modern
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\SharpLMS.exe
UninstallDisplayName=Sharp Associates LMS
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "C:\Temp\SharpBuild\dist\SharpLMS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.db,branches\*,branches"

[Icons]
Name: "{group}\Sharp Associates LMS"; Filename: "{app}\SharpLMS.exe"; IconFilename: "{app}\SharpLMS.exe"
Name: "{userdesktop}\Sharp Associates LMS"; Filename: "{app}\SharpLMS.exe"; IconFilename: "{app}\SharpLMS.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\SharpLMS.exe"; Description: "Launch Sharp Associates LMS now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
