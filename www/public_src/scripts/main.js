angular.module('aiddataDET', ['ngRoute', 'ui.bootstrap'])
.config(function($routeProvider) {
  $routeProvider
    .when('/', {
      templateUrl: 'views/pages/homepage.html'
    })
    .otherwise({
      redirectTo: '/'
    });
});
