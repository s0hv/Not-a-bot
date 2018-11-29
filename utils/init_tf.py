class LoadedModel:
    def __init__(self, session, graph, model, chars, vocab):
        """
        Initialise the model loaded in this file for future use.
        Intended for use with init_tf unless you know what you are doing

        Args:
            session (tensorflow.Session): The session used to load the model
            graph (tensorflow.Graph): The graph used to load the model
            model (char_rnn.model.Model): The model that was loaded
            chars: Unpickled stuff
            vocab: Unpickled stuff
        """
        self._sess = session
        self._graph = graph
        self._model = model
        self._chars = chars
        self._vocab = vocab

    @property
    def sess(self):
        return self._sess

    @property
    def model(self):
        return self._model

    @property
    def chars(self):
        return self._chars

    @property
    def vocab(self):
        return self._vocab

    @property
    def graph(self):
        return self._graph

    def sample(self, prime=None, n=100, sample=1):
        """
        Sample text. The last step of sample.py in the original char-rnn

        Args:
            prime (str): Prime text
            n (int): Amount of characters to sample
            sample (int):
                0 to use max at each timestep, 1 to sample at
                each timestep, 2 to sample on spaces

        Returns:
            str: Text that was generated as utf-8
        """
        if not prime:
            prime = self.chars[0]

        with self.graph.as_default():
            return self.model.sample(self.sess, self.chars,
                                         self.vocab,
                                         n, prime, sample)


def init_tf():
    import os
    import tensorflow as tf
    from char_rnn.model import Model
    from six.moves import cPickle

    # Models should be in data/models
    save_dir = os.path.join(os.getcwd(), 'data', 'models')

    with open(os.path.join(save_dir, 'config.pkl'), 'rb') as f:
        saved_args = cPickle.load(f)
    with open(os.path.join(save_dir, 'chars_vocab.pkl'), 'rb') as f:
        chars, vocab = cPickle.load(f)

    graph = tf.get_default_graph()
    with graph.as_default():
        model = Model(saved_args, training=False)
        sess = tf.Session()
        with sess.as_default() as sess:
            tf.global_variables_initializer().run()
            saver = tf.train.Saver(tf.global_variables())
            ckpt = tf.train.get_checkpoint_state(save_dir)

            if ckpt and ckpt.model_checkpoint_path:
                saver.restore(sess, ckpt.model_checkpoint_path)

    return LoadedModel(sess, graph, model, chars, vocab)
