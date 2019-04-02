from settings import *

with open(testfile, encoding='utf8') as fp:
	for i, line in enumerate(fp):
		s = line.strip()
		print(i, s)
		print(s.encode("cp1251")
