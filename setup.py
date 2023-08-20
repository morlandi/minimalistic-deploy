import os
import re
from setuptools import setup


def get_version(*file_paths):
    """Retrieves the version from specific file"""
    filename = os.path.join(os.path.dirname(__file__), *file_paths)
    version_file = open(filename).read()
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", version_file, re.M)
    if version_match:
        return version_match.group(1)
    raise RuntimeError('Unable to find version string.')


version = get_version("minimalistic_deploy", "__init__.py")
readme = open('README.md').read()
history = open('HISTORY.md').read().replace('.. :changelog:', '')


setup(name='minimalistic-deploy',
      version=version,
      description='Minimalistic support to deploy a Django project via SSH',
      long_description=readme + '\n\n' + history,
      long_description_content_type='text/markdown',
      classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.8',
        'Framework :: Django :: 4.0',
        'Topic :: System :: Software Distribution',
      ],
      keywords='deployment',
      url='https://github.com/morlandi/minimalistic-deploy',
      author='Mario Orlandi',
      author_email='morlandi@brainstorm.it',
      license='MIT',
      scripts=['bin/deploy'],
      packages=['minimalistic_deploy'],
      install_requires=[
        "Jinja2 >= 3.1.2",
        "rich >= 13.5.2",
      ],
      include_package_data=False,
      zip_safe=False)
