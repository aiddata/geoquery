angular.module('aiddataDET', ['ui.router', 'ui.bootstrap', 'angucomplete-alt', 'ngMaterial'])
.config(function($stateProvider, $urlRouterProvider) {

  $urlRouterProvider.otherwise("/");

  $stateProvider
      .state('map', {
        url: '/',
        templateUrl: 'views/pages/map.html'
      })
      .state('search', {
        url: '/search/:boundary/:subboundary',
        templateUrl: 'views/pages/search.html'
      })
      .state('submit', {
        url: '/submit',
        templateUrl: 'views/pages/submit.html'
      })
      .state('status', {
        url: '/status',
        templateUrl: 'views/pages/status.html'
      });
});
