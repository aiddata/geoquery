angular.module('aiddataDET', ['ui.router', 'ui.bootstrap', 'angucomplete-alt'])
.config(function($stateProvider, $urlRouterProvider) {

  $urlRouterProvider.otherwise("/");

  $stateProvider
      .state('map', {
        url: '/',
        templateUrl: 'views/pages/map.html'
      })
      .state('search', {
        url: '/search/:geomId',
        templateUrl: 'views/pages/search.html',
        controller: function ($scope, $stateParams) {
          $scope.geomId = $stateParams.geomId;
        }
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
