angular.module('aiddataDET', ['ngRoute'])
.config(function($routeProvider) {
  $routeProvider
    .when('/', {
      templateUrl: 'views/pages/homepage.html'
    })
    .otherwise({
      redirectTo: '/'
    });
});
