angular.module('aiddataDET')
  .service('routingService', function(ajaxFactory, $log, $q, $rootScope, queryFactory) {

    this.verifyDataset = function($state, $stateParams, datasets) {
      return $q.when(datasets)
        .then(function(sets) {
          var setExists = _.chain(sets)
            .filter(function(set) {
              return set.title === $stateParams.dataset ||
                set.name === $stateParams.dataset;
            })
            .size()
            .gte(1)
            .value();

          return setExists ? true : $q.reject('Could Not Find Dataset');
        })
        .then(function() {
          return queryFactory.setDataset($stateParams.dataset);
        })
        .catch(function(err) {
          $log.error(err);
          $stateParams.dataset = '';
          return $state.go('search', $stateParams, { reload: true });
        });
    };

  });
