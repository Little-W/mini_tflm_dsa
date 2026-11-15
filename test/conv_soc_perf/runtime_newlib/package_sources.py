"""Pinned upstream source/package identities for the optional memory runtime.

These are source provenance constants, not generated test vectors or results.
Actual compiler/library/execution hashes are written by build.py to --out.
"""
NEWLIB_VERSION = '4.5.0.20241231'
SOURCE_ARCHIVE_PREFIX = 'newlib-4.5.0.20241231/'
PACKAGES = [{'filename': 'gcc-riscv64-unknown-elf_14.2.0+19_amd64.deb',
  'url': 'https://deb.debian.org/debian/pool/main/g/gcc-riscv64-unknown-elf/gcc-riscv64-unknown-elf_14.2.0+19_amd64.deb',
  'sha256': 'c5637d336d9bb18dcba60c6cdee40a61a55eb45f7a5637bce00ecdc47b8295dc',
  'bytes': 60956544,
  'package_fields': 'Package: gcc-riscv64-unknown-elf\nVersion: 14.2.0+19\nArchitecture: amd64'},
 {'filename': 'binutils-riscv64-unknown-elf_2.44-3+7+b1_amd64.deb',
  'url': 'https://deb.debian.org/debian/pool/main/b/binutils-riscv64-unknown-elf/binutils-riscv64-unknown-elf_2.44-3+7+b1_amd64.deb',
  'sha256': '5e2d6b9fd803b475be267917ce543e79d3894026132aba91488736e6b17144a3',
  'bytes': 2928704,
  'package_fields': 'Package: binutils-riscv64-unknown-elf\n'
                    'Version: 2.44-3+7+b1\n'
                    'Architecture: amd64'},
 {'filename': 'libnewlib-dev_4.5.0.20241231-1_all.deb',
  'url': 'https://deb.debian.org/debian/pool/main/n/newlib/libnewlib-dev_4.5.0.20241231-1_all.deb',
  'sha256': 'feb2ed49a464b0346e42c3506088a41025273bff5f8e6bc5777afeac3704b3c1',
  'bytes': 263176,
  'package_fields': 'Package: libnewlib-dev\nVersion: 4.5.0.20241231-1\nArchitecture: all'},
 {'filename': 'newlib_4.5.0.20241231.orig.tar.gz',
  'url': 'https://deb.debian.org/debian/pool/main/n/newlib/newlib_4.5.0.20241231.orig.tar.gz',
  'sha256': '33f12605e0054965996c25c1382b3e463b0af91799001f5bb8c0630f2ec8c852',
  'bytes': 9081514}]
SOURCE_SHA256 = {'COPYING.NEWLIB': 'fcfb5ec69b6ab52676dcc4dab7cf4338c8000ef97812dadd35b8592a640a8419',
 'newlib/libc/ctype/local.h': '360cfc0a34fcc3462fb63c80a6980919a3b1c46fb5fa95e768efe9af6f92183b',
 'newlib/libc/locale/setlocale.h': 'cd567f8dba5892dce2c017f360a707a8c4af6f68951ed87de53faa4f30c729c0',
 'newlib/libc/machine/riscv/memcpy.c': '0b6081ad1bb60cc526147b9fd7a78ff6e148d7c83d91d0c96b77d598ff9b9f76',
 'newlib/libc/machine/riscv/memset.S': 'd19ba6175bfac8114dc828a8e4029080d0a86c926f0bf12daa3bc44550adaa62',
 'newlib/libc/string/local.h': 'a2f48fa7faa2faac92fc3360035636a272f5be9b658e80cb810ee8cf2b6f82c3'}
