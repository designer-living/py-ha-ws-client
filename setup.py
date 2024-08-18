from setuptools import setup

version = '0.6'

with open("README.md", "rb") as f:
    long_descr = f.read().decode("utf-8")

setup(
    name='py_ha_ws_client',
    packages=['py_ha_ws_client'],
    version=version,
    license='Apache 2.0',
    description='A Python client to make it easy to connect and consume data from the Home Assistant web socket API.',
    long_description=long_descr,
    long_description_content_type='text/markdown',
    author='foxy82',
    author_email='foxy82.github@gmail.com',
    url='https://github.com/designer-living/py-ha-ws-client',
    download_url=f'https://github.com/designer-living/py-ha-ws-client/archive/{version}.tar.gz',
    keywords=['Home Assistant', 'Websocket'],
    install_requires=[
        "ws4py==0.5.1"
    ],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3.10'
    ],
)
