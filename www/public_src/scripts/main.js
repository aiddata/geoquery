angular.module('aiddataDET', ['ngRoute', 'ui.bootstrap', 'angucomplete-alt'])
.config(function($routeProvider) {
  $routeProvider
    .when('/', {
      templateUrl: 'views/pages/homepage.html'
    })
    .otherwise({
      redirectTo: '/'
    });
});
