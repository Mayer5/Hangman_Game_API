# -*- coding: utf-8 -*-`
"""api.py - Create and configure the Game API exposing the resources.
This can also contain game logic. For more complex games it would be wise to
move game logic to another file. Ideally the API will be simple, concerned
primarily with communication to/from the API's users."""

import random
import logging
import endpoints
from protorpc import remote, messages
from google.appengine.api import memcache
from google.appengine.ext import ndb
from google.appengine.api import taskqueue

from models import User, Game, Score
from models import StringMessage, NewGameForm, GameForm, MakeMoveForm,\
    ScoreForms, GameForms, UserForm, UserForms
from utils import get_by_urlsafe
import re

NEW_GAME_REQUEST = endpoints.ResourceContainer(NewGameForm)
GET_GAME_REQUEST = endpoints.ResourceContainer(
        urlsafe_game_key=messages.StringField(1),)
MAKE_MOVE_REQUEST = endpoints.ResourceContainer(
    MakeMoveForm,
    urlsafe_game_key=messages.StringField(1),)
USER_REQUEST = endpoints.ResourceContainer(user_name=messages.StringField(1),
                                           email=messages.StringField(2))
GET_HIGH_SCORES_REQUEST = endpoints.ResourceContainer(
    results=messages.IntegerField(1))

MEMCACHE_MOVES_REMAINING = 'MOVES_REMAINING'


# @endpoints.api(name='hangman', version='v1', audiences=[ANDROID_AUDIENCE],
#     allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID, ANDROID_CLIENT_ID, IOS_CLIENT_ID],
#     scopes=[EMAIL_SCOPE])
@endpoints.api(name='hangman', version='v1')
class HangmanApi(remote.Service):
    """Game API"""
    @endpoints.method(request_message=USER_REQUEST,
                      response_message=StringMessage,
                      path='user',
                      name='create_user',
                      http_method='POST')
    def create_user(self, request):
        """Create a User. Requires a unique username"""
        if User.query(User.name == request.user_name).get():
            raise endpoints.ConflictException(
                    'A User with that name already exists!')
        """ import function from regex used to check email validity"""
        user = User(name=request.user_name, email=request.email)
        match = re.match('^[_a-z0-9-]+(\.[_a-z0-9-]+)*@[a-z0-9-]'
                         '+(\.[a-z0-9-]+)*(\.[a-z]{2,4})$', request.email)
        
        if match is None:
            print('invalid email entry')
            raise ValueError('Bad Syntax')
        user.put()
        return StringMessage(message='User {} created!'.format(
                request.user_name))

    @endpoints.method(request_message=NEW_GAME_REQUEST,
                      response_message=GameForm,
                      path='game',
                      name='new_game',
                      http_method='POST')
    def new_game(self, request):
        """Creates new game"""
        user = User.query(User.name == request.user_name).get()
        if not user:
            raise endpoints.NotFoundException(
                    'A User with that name does not exist!')
        try:
            game = Game.new_game(user.key, 9)
        except ValueError:
            raise endpoints.BadRequestException('error message')

        # Use a task queue to update the average attempts remaining.
        # This operation is not needed to complete the creation of a new game
        # so it is performed out of sequence.
        taskqueue.add(url='/tasks/cache_average_attempts')
        return game.to_form('Good luck playing Hangman!')

    @endpoints.method(request_message=MAKE_MOVE_REQUEST,
                      response_message=GameForm,
                      path='game/{urlsafe_game_key}',
                      name='make_move',
                      http_method='PUT')
    def make_move(self, request):
        """Makes a move. Returns a game state with message"""
        game = get_by_urlsafe(request.urlsafe_game_key, Game)
        if game.game_over:
            return game.to_form('Game already over!')
        """code added to check letter has not already been guessed"""
        if request.guess in game.letters_guessed:
            raise endpoints.BadRequestException('repeated letter')
        game.letters_guessed += request.guess
        failed = 0
        for char in game.secret:
            if char not in game.letters_guessed:
                failed += 1
            if failed == 0:
                game.end_game(True)
                return game.to_form('You win!')
            if request.guess in game.secret:
                msg = 'Your letter is in the secret word'
                game.history.append((request.guess, " found"))
                """ append the move to the game history"""
            else:
                game.attempts_remaining -= 1
                game.history.append((request.guess, "not in word"))
                """ appned the move to the game history"""
                msg = 'letter not there, another piece to the hangman'
            if game.attempts_remaining == 0:
                game.end_game(False)
                return game.to_form(msg + ' Game over!')
            else:
                game.put()
        return game.to_form(msg)

    @endpoints.method(request_message=GET_GAME_REQUEST,
                      response_message=StringMessage,
                      path='game/{urlsafe_game_key}/history',
                      name='get_game_history',
                      http_method='GET')
    def get_game_history(self, request):
        """Returns a Game's history"""
        game = get_by_urlsafe(request.urlsafe_game_key, Game)
        if not game:
            raise endpoints.NotFoundException('Game not found!')
        return StringMessage(message=str(game.history))

    @endpoints.method(request_message=GET_GAME_REQUEST,
                      response_message=GameForm,
                      path='game/{urlsafe_game_key}',
                      name='get_game',
                      http_method='GET')
    def get_game(self, request):
        """Return the current game state."""
        game = get_by_urlsafe(request.urlsafe_game_key, Game)
        if game:
            return game.to_form('Here is the requested game')
        else:
            raise endpoints.NotFoundException('Game not found!')

    @endpoints.method(request_message=USER_REQUEST,
                      response_message=GameForms,
                      path='user/games',
                      name='get_user_games',
                      http_method='GET')
    def get_games(self, request):
        """Return all games"""
        user = User.query(User.name == request.user_name).get()
        if not user:
            raise endpoints.NotFoundException('User not found')
        games = Game.query(Game.user == user.key).\
            filter(Game.game_over is False)
        return GameForms(items=[game.to_form("active game") for game in games])
     
    @endpoints.method(request_message=GET_GAME_REQUEST,
                      response_message=StringMessage,
                      path='game/{urlsafe_game_key}',
                      name='cancel_game',
                      http_method='DELETE')
    def cancel_game(self, request):
        """ Remove and kill game that has not ended"""
        game = get_by_urlsafe(request.urlsafe_game_key, Game)
        if game and not game.game_over:
            game.key.delete()
            return StringMessage(message='Game id key:{} removed'.format(
                request.urlsafe_game_key))
        elif game and game.game_over:
            raise endpoints.BadRequestException(
                'Sorry cannot delete completed games')
        else:
            raise endpoints.NotFoundException('No such game found')

    @endpoints.method(response_message=ScoreForms,
                      path='scores',
                      name='get_scores',
                      http_method='GET')
    def get_scores(self, request):
        """Return all scores"""
        return ScoreForms(items=[score.to_form() for score in Score.query()])

    @endpoints.method(request_message=GET_HIGH_SCORES_REQUEST,
                      response_message=ScoreForms,
                      path='high_scores',
                      name='get_high_scores',
                      http_method='GET')
    def get_high_scores(self, request):
        """Return scores graded out from highest"""
        Scores = Score.query(Score.won is True).order(Score.guesses).fetch(
            request.results)
        return ScoreForms(items=[score.to_form() for score in Scores])

    @endpoints.method(response_message=UserForms,
                      path='user/rankings',
                      name='get_user_rankings',
                      http_method='GET')
    def get_user_rankings(self, request):
        """Return graded user user_rankings on win ratios"""
        users = User.query(User.total_played > 0).fetch()
        users = sorted(users, key=lambda x: x.win_percentage, reverse=True)
        return UserForms(items=[user.to_form() for user in users])

    @endpoints.method(request_message=USER_REQUEST,
                      response_message=ScoreForms,
                      path='scores/user/{user_name}',
                      name='get_user_scores',
                      http_method='GET')
    def get_user_scores(self, request):
        """Returns all of an individual User's scores"""
        user = User.query(User.name == request.user_name).get()
        if not user:
            raise endpoints.NotFoundException(
                    'A User with that name does not exist!')
        scores = Score.query(Score.user == user.key)
        return ScoreForms(items=[score.to_form() for score in scores])

    @endpoints.method(response_message=StringMessage,
                      path='games/average_attempts',
                      name='get_average_attempts_remaining',
                      http_method='GET')
    def get_average_attempts(self, request):
        """Get the cached average moves remaining"""
        return StringMessage(message=memcache.get(
            MEMCACHE_MOVES_REMAINING) or '')

    @staticmethod
    def _cache_average_attempts():
        """Populates memcache with the average moves remaining of Games"""
        games = Game.query(Game.game_over is False).fetch()
        if games:
            count = len(games)
            total_attempts_remaining = sum(
                [game.attempts_remaining for game in games])
            average = float(total_attempts_remaining)/count
            memcache.set(MEMCACHE_MOVES_REMAINING,
                         'The average moves remaining is {:.2f}'.
                         format(average))


api = endpoints.api_server([HangmanApi])
