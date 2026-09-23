using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using SoulsFormats;

var src = @"V:\games\Elden Ring\Game\mod\script\473000_battle.luabnd.dcx";
var outDir = @"V:\1_mel\Ringrandom\cnv_randomizer\output\runtime\_radahn_ai";
Directory.CreateDirectory(outDir);
var bnd = BND4.Read(src);
foreach (var f in bnd.Files)
{
    var name = Path.GetFileName(f.Name.Replace('\\','/'));
    var path = Path.Combine(outDir, name);
    File.WriteAllBytes(path, f.Bytes);
    Console.WriteLine($"{name} {f.Bytes.Length}");
    if (name.EndsWith(".lua", StringComparison.OrdinalIgnoreCase))
    {
        var text = Encoding.UTF8.GetString(f.Bytes);
        // dump key sections
        File.WriteAllText(Path.Combine(outDir, name + ".txt"), text);
    }
}
