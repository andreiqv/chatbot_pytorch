import os
######### 
data_dir = '../data'
#save_dir = "/mnt/video/tmp/save"
save_dir = "../save"
#corpus_name = "corpus"
# Define path to new file
corpus_name = 'corpus'
corpus = os.path.join(data_dir, corpus_name)
#datafile = os.path.join(corpus, "formatted_movie_lines.txt")
datafile = os.path.join(data_dir, "rus_subs/train.utf")
testfile = os.path.join(data_dir, "test_answers.utf")

MAX_LENGTH = 10  # Maximum sentence length to consider