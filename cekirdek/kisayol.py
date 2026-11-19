"""Yumi kısayolu (17 Kasım): Masaüstü + Başlat menüsü, Yumi logosu (assets/yumi.ico), konsolsuz (pythonw),
görev çubuğu kimliği APP_ID (launch.py aynı kimliği kullanır → sabitlenen kısayol ve açık pencere tek simge).
Kullanım: python -c "import kisayol; print(kisayol.olustur())"   (setup_local.py kurulumda çağırır)"""
import ctypes, subprocess
from pathlib import Path
from app_paths import ROOT, APP_ID, data_dir

_PS = r'''param($lnk,$hedef,$arg,$dizin,$ikon,$aciklama,$appid)
$ErrorActionPreference='Stop'
Add-Type -TypeDefinition @"
using System; using System.Text; using System.Runtime.InteropServices;
[ComImport, Guid("00021401-0000-0000-C000-000000000046")] class CShellLink {}
[ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("000214F9-0000-0000-C000-000000000046")]
interface IShellLinkW {
 void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder f, int c, IntPtr fd, uint fl);
 void GetIDList(out IntPtr p); void SetIDList(IntPtr p);
 void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int c);
 void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string s);
 void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int c);
 void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string s);
 void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int c);
 void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string s);
 void GetHotkey(out short h); void SetHotkey(short h);
 void GetShowCmd(out int i); void SetShowCmd(int i);
 void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int c, out int i);
 void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string s, int i);
 void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string s, uint r);
 void Resolve(IntPtr h, uint f);
 void SetPath([MarshalAs(UnmanagedType.LPWStr)] string s);
}
[ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("0000010b-0000-0000-C000-000000000046")]
interface IPersistFileY { void GetClassID(out Guid g); [PreserveSig] int IsDirty();
 void Load([MarshalAs(UnmanagedType.LPWStr)] string f, uint m);
 void Save([MarshalAs(UnmanagedType.LPWStr)] string f, bool r);
 void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string f); void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string f); }
[StructLayout(LayoutKind.Sequential, Pack=4)] public struct PKEY { public Guid fmtid; public uint pid; }
[StructLayout(LayoutKind.Explicit)] public struct PVAR { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; [FieldOffset(16)] public IntPtr pad; }
[ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
interface IPropertyStore { void GetCount(out uint c); void GetAt(uint i, out PKEY k);
 void GetValue(ref PKEY k, out PVAR v); void SetValue(ref PKEY k, ref PVAR v); void Commit(); }
public static class YumiLnk {
 public static void Yap(string lnk,string hedef,string arg,string dizin,string ikon,string aciklama,string appid){
  var l=(IShellLinkW)new CShellLink(); l.SetPath(hedef); l.SetArguments(arg); l.SetWorkingDirectory(dizin);
  l.SetIconLocation(ikon,0); l.SetDescription(aciklama);
  var ps=(IPropertyStore)l; var k=new PKEY{fmtid=new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"),pid=5};
  var v=new PVAR{vt=31,p=Marshal.StringToCoTaskMemUni(appid)}; ps.SetValue(ref k, ref v); ps.Commit(); Marshal.FreeCoTaskMem(v.p);
  ((IPersistFileY)l).Save(lnk,true);
 }
}
"@
[YumiLnk]::Yap($lnk,$hedef,$arg,$dizin,$ikon,$aciklama,$appid)
'''


def _klasor(csidl):
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return Path(buf.value)


def olustur(masaustu=True, baslat=True):
    """Kısayolları oluşturur/yeniler; yazılan .lnk yollarını döner."""
    hedef = ROOT / '.venv' / 'Scripts' / 'pythonw.exe'
    ikon = ROOT / 'assets' / 'yumi.ico'
    if not hedef.exists() or not ikon.exists():
        raise FileNotFoundError(f'{hedef if not hedef.exists() else ikon} yok')
    ps1 = data_dir() / 'onbellek' / 'kisayol.ps1'
    ps1.parent.mkdir(parents=True, exist_ok=True)
    ps1.write_text(_PS, encoding='utf-8-sig')
    yerler = ([_klasor(0x10)] if masaustu else []) + ([_klasor(0x02)] if baslat else [])  # Masaüstü, Başlat > Programlar
    yazilan = []
    for klasor in yerler:
        lnk = klasor / 'Yumi.lnk'
        subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ps1),
                        '-lnk', str(lnk), '-hedef', str(hedef), '-arg', f'"{ROOT / "launch.py"}"',
                        '-dizin', str(ROOT), '-ikon', str(ikon), '-aciklama', 'Yumi masaüstü asistanı', '-appid', APP_ID],
                       check=True, capture_output=True, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        yazilan.append(str(lnk))
    return yazilan
