angular.module('aiddataDET', ['ui.router', 'ui.bootstrap', 'angucomplete-alt'])
.config(function($stateProvider, $urlRouterProvider) {

  $urlRouterProvider.otherwise("/");

  $stateProvider
      .state('map', {
        url: '/',
        templateUrl: 'views/pages/map.html'
      })
      .state('search', {
        url: '/search/:boundary/:subboundary?datatype',
        templateUrl: 'views/pages/search.html',
        controller: function($rootScope, $scope, $state, $stateParams) {
          $rootScope.$on('dataset:selected', function(e, data) {
            $scope.datatype = $state.params.datatype;
          });
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
