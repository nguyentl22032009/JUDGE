from setuptools import setup, Extension

# Định nghĩa module C
checker_module = Extension(
    '_checker',  # Tên module khi import trong Python (phải khớp với PyInit__checker)
    sources=['_checker.c'],  # File nguồn C
    include_dirs=['C:\\Users\\KN\\AppData\\Local\\Programs\\Python\\Python313\\include'],  # Thay '3.x' bằng phiên bản Python của bạn (ví dụ: 3.11)
)

# Cấu hình setup
setup(
    name='checker',
    version='1.0',
    description='DMOJ Checker Module',
    ext_modules=[checker_module],
)