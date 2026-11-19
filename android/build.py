"""Build a signed APK with Google's SDK tools and a JDK; no Gradle downloads."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
FONTS = PROJECT/'assets/fonts'
FONT_RESOURCES = {
    'Anton-Regular.ttf': 'anton.ttf',
    'ChakraPetch-Regular.ttf': 'chakra_petch.ttf',
    'ChakraPetch-SemiBold.ttf': 'chakra_petch_semibold.ttf',
}


def main():
    parser = argparse.ArgumentParser()
    sdk_default = os.getenv('ANDROID_HOME') or os.getenv('ANDROID_SDK_ROOT')
    parser.add_argument('--sdk', type=Path, default=sdk_default)
    args = parser.parse_args()
    if not args.sdk:
        parser.error('Set ANDROID_HOME or pass --sdk SDK_DIRECTORY.')
    sdk = args.sdk.resolve()
    candidates = list((sdk/'build-tools').glob('*'))+[sdk/'android-15']
    tools = next((p for p in reversed(sorted(candidates)) if (p/'aapt2.exe').exists()), None)
    platforms = list((sdk/'platforms').glob('android-*'))+[sdk/'android-35']
    platform = next((p/'android.jar' for p in reversed(sorted(platforms)) if (p/'android.jar').exists()), None)
    if not tools or not platform:
        raise SystemExit('Install Android platform 35 and build-tools 35.0.0, then pass --sdk SDK_DIRECTORY.')
    if not os.getenv('JAVA_HOME'):
        raise SystemExit('Set JAVA_HOME to your JDK installation.')
    java_home = Path(os.environ['JAVA_HOME'])
    java, javac, keytool = (java_home/'bin'/name for name in ('java.exe','javac.exe','keytool.exe'))
    library = ROOT/'libs/core-3.5.3.jar'
    if not library.exists():
        raise SystemExit('Missing android/libs/core-3.5.3.jar. See android/README.md.')
    data = PROJECT/'data'
    data.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='android-build-', dir=data) as directory:
        build_apk(Path(directory), tools, platform, java, javac, keytool, library)


def build_apk(build, tools, platform, java, javac, keytool, library):
    for name in ('generated','classes','dex'):
        (build/name).mkdir(parents=True, exist_ok=True)
    res = build/'res'
    shutil.copytree(ROOT/'app/src/main/res', res)
    (res/'font').mkdir()
    for filename, resource in FONT_RESOURCES.items():
        shutil.copyfile(FONTS/filename, res/'font'/resource)
    env = os.environ.copy()
    def run(stage, command):
        print(stage, flush=True)
        subprocess.run([str(value) for value in command], check=True, env=env)
    run('Compiling Android resources', [tools/'aapt2.exe','compile','--dir',res,'-o',build/'compiled.zip'])
    run('Linking Android resources', [tools/'aapt2.exe','link','--manifest',ROOT/'app/src/main/AndroidManifest.xml',
        '-I',platform,'--java',build/'generated','--min-sdk-version','26','--target-sdk-version','35',
        '--rename-manifest-package','com.behavioralguard.companion.v2','--custom-package','com.behavioralguard.companion',
        '-o',build/'resources.apk',build/'compiled.zip'])
    sources = list((ROOT/'app/src/main/java').rglob('*.java'))+list((build/'generated').rglob('*.java'))
    run('Compiling phone code', [javac,'-encoding','UTF-8','-source','8','-target','8','-bootclasspath',str(platform)+os.pathsep+str(tools/'core-lambda-stubs.jar'),
        '-classpath',library,'-d',build/'classes',*sources])
    with zipfile.ZipFile(build/'classes.jar','w') as archive:
        for file in (build/'classes').rglob('*.class'):
            archive.write(file,file.relative_to(build/'classes').as_posix())
    run('Compiling Android bytecode', [java,'-cp',tools/'lib/d8.jar','com.android.tools.r8.D8','--min-api','26',
        '--lib',platform,'--output',build/'dex',build/'classes.jar',library])
    shutil.copyfile(build/'resources.apk',build/'unsigned.apk')
    with zipfile.ZipFile(build/'unsigned.apk','a') as archive:
        for dex in (build/'dex').glob('*.dex'):
            archive.write(dex,dex.name,compress_type=zipfile.ZIP_STORED)
        for notice in (ROOT/'LICENSE-ZXING.txt',ROOT/'NOTICE-ZXING.txt'):
            if notice.exists():
                archive.write(notice,'assets/'+notice.name)
        for notice in (FONTS/'Anton-OFL.txt', FONTS/'ChakraPetch-OFL.txt'):
            archive.write(notice, 'assets/licenses/'+notice.name)
    run('Aligning APK', [tools/'zipalign.exe','-f','4',build/'unsigned.apk',build/'aligned.apk'])
    signing = PROJECT/'data/android-signing'
    signing.mkdir(parents=True,exist_ok=True)
    password_file = signing/'signing.json'
    if password_file.exists():
        password = json.loads(password_file.read_text())['password']
    else:
        password = secrets.token_urlsafe(32)
        password_file.write_text(json.dumps({'password':password}))
    env['BG_SIGN_PASSWORD'] = password
    store = signing/'phone-signing.p12'
    if not store.exists():
        run('Creating app signing key', [keytool,'-genkeypair','-keystore',store,'-storetype','PKCS12',
            '-alias','behavioral-guard','-keyalg','RSA','-keysize','3072','-validity','10000',
            '-storepass:env','BG_SIGN_PASSWORD','-dname','CN=Behavioral Guard, OU=Capstone'])
    output = PROJECT/'BehavioralGuard.apk'
    run('Signing APK', [java,'-jar',tools/'lib/apksigner.jar','sign','--ks',store,
        '--ks-key-alias','behavioral-guard','--ks-pass','env:BG_SIGN_PASSWORD','--out',output,build/'aligned.apk'])
    run('Verifying APK signature', [java,'-jar',tools/'lib/apksigner.jar','verify','--verbose',output])
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None and 'classes.dex' in archive.namelist()
    print('Built:',output,flush=True)


if __name__ == '__main__':
    main()
