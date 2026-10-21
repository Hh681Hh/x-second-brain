"""Package original MV3 source for local loading, with no user data or credentials."""
import argparse
from pathlib import Path
import shutil
import zipfile

SOURCE=Path(__file__).resolve().parents[1]/'xsecondbrain'/'browser_extension'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--unpacked',type=Path)
    args=parser.parse_args()
    if args.output.exists() or (args.unpacked and args.unpacked.exists()):
        raise SystemExit('目标已存在，请选择新文件名或文件夹；不会覆盖。')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(args.output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(SOURCE.iterdir()):
            if source.is_file():archive.write(source,'x-bookmark-clipper/'+source.name)
    if args.unpacked:shutil.copytree(SOURCE,args.unpacked)
    print(args.output.resolve())
    if args.unpacked:print(args.unpacked.resolve())


if __name__=='__main__':main()
